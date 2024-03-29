import io
import os
from builtins import ValueError
import pandas as pd
import numpy as np
from typing import Union,Tuple

from sudio.audioutils.audio import Audio
from sudio.audioutils.sync import synchronize_audio
from sudio.extras.timed_indexed_string import TimedIndexedString
from sudio.types import DecodeError


def write_to_cached_file(*head,
                         head_dtype: str = 'u8',
                         data: Union[bytes, io.BufferedRandom] = None,
                         file_name: str = None,
                         file_mode: str = 'wb+',
                         buffered_random: io.BufferedRandom = None,
                         pre_truncate: bool = False,
                         pre_seek: Tuple[int, int] = None,
                         after_seek: Tuple[int, int] = None,
                         pre_flush: bool = False,
                         after_flush: bool = False,
                         size_on_output: bool = False,
                         data_chunk: int = int(1e6)) -> Union[io.BufferedRandom, Tuple[io.BufferedRandom, int]]:
    """
    Writes data to a cached file with optional pre-processing and post-processing steps.

    Parameters:
    - *head: Variable number of arguments to be written at the beginning of the file.
    - head_dtype: Data type for the head arguments (default: 'u8').
    - data: Bytes or BufferedRandom object to be written to the file.
    - file_name: Name of the file. If not provided, a BufferedRandom object must be provided.
    - file_mode: File mode for opening the file (default: 'wb+').
    - buffered_random: BufferedRandom object for writing data.
    - pre_truncate: Truncate the file before writing (default: False).
    - pre_seek: Tuple (offset, whence) to seek to before writing.
    - after_seek: Tuple (offset, whence) to seek to after writing.
    - pre_flush: Flush the file before writing (default: False).
    - after_flush: Flush the file after writing (default: False).
    - size_on_output: If True, returns a tuple of the file object and the total size written (default: False).
    - data_chunk: Size of the data chunks to read when writing BufferedRandom data (default: 1e6).

    Returns:
    - io.BufferedRandom or Tuple of io.BufferedRandom and int (if size_on_output is True).
    """
    if buffered_random:
        file: io.BufferedRandom = buffered_random
    elif file_name:
        file = open(file_name, file_mode)
    else:
        raise ValueError("Either buffered_random or file_name must be provided.")
    size = 0

    if pre_seek:
        file.seek(*pre_seek)

    if pre_truncate:
        file.truncate()

    if pre_flush:
        file.flush()

    if head:
        size = file.write(np.asarray(head, dtype=head_dtype))

    if data:
        if isinstance(data, io.BufferedRandom):
            buffer = data.read(data_chunk)
            while buffer:
                size += file.write(buffer)
                buffer = data.read(data_chunk)
        else:
            size += file.write(data)

    if after_seek:
        file.seek(*after_seek)

    if after_flush:
        file.flush()

    if size_on_output:
        return file, size
    return file


def handle_cached_record(record: Union[pd.Series, dict],
                         path_server: TimedIndexedString,
                         master_obj,
                         decoder: callable = None,
                         sync_sample_format_id: int = None,
                         sync_nchannels: int = None,
                         sync_sample_rate: int = None,
                         safe_load: bool = True) -> pd.Series:
    """
    Handles caching of audio records, ensuring synchronization and safe loading.

    Parameters:
    - record: Audio record as a pandas Series or dictionary.
    - path_server: TimedIndexedString object for generating unique paths.
    - master_obj: Object managing the audio cache.
    - decoder: Callable function for decoding audio if needed.
    - sync_sample_format_id: Synchronized sample format ID.
    - sync_nchannels: Synchronized number of channels.
    - sync_sample_rate: Synchronized sample rate.
    - safe_load: If True, ensures safe loading in case of errors.

    Returns:
    - Modified audio record as a pandas Series.
    """
    sync_sample_format_id = master_obj._sample_format if sync_sample_format_id is None else sync_sample_format_id
    sync_nchannels = master_obj.nchannels if sync_nchannels is None else sync_nchannels
    sync_sample_rate = master_obj._sample_rate if sync_sample_rate is None else sync_sample_rate

    path: str = path_server()
    cache = master_obj._cache()
    try:
        if path in cache:
            try:
                os.rename(path, path)
                f = record['o'] = open(path, 'rb+')
            except OSError:
                while True:
                    new_path: str = path_server()
                    try:
                        if os.path.exists(new_path):
                            os.rename(new_path, new_path)
                            f = record['o'] = open(new_path, 'rb+')
                        else:
                            # Write a new file based on the new path
                            data_chunk = int(1e7)
                            with open(path, 'rb+') as pre_file:
                                f = record['o'] = open(new_path, 'wb+')
                                data = pre_file.read(data_chunk)
                                while data:
                                    f.write(data)
                                    data = pre_file.read(data_chunk)
                            break
                    except OSError:
                        # If data already opened in another process, continue trying
                        continue

            f.seek(0, 0)
            cache_info = f.read(master_obj.__class__.CACHE_INFO)
            try:
                csize, cframe_rate, csample_format, cnchannels = np.frombuffer(cache_info, dtype='u8').tolist()
            except ValueError:
                # Handle bad cache error
                f.close()
                os.remove(f.name)
                raise DecodeError

            csample_format = csample_format if csample_format else None
            record['size'] = csize

            record['frameRate'] = cframe_rate
            record['nchannels'] = cnchannels
            record['sampleFormat'] = csample_format

            if (cnchannels == sync_nchannels and
                    csample_format == sync_sample_format_id and
                    cframe_rate == sync_sample_rate):
                pass

            elif safe_load:
                # Load data safely and synchronize audio
                record['o'] = f.read()
                record = synchronize_audio(record,
                                            sync_nchannels,
                                            sync_sample_rate,
                                            sync_sample_format_id)

                f = record['o'] = write_to_cached_file(record['size'],
                                                       record['frameRate'],
                                                       record['sampleFormat'] if record['sampleFormat'] else 0,
                                                       record['nchannels'],
                                                       buffered_random=f,
                                                       data=record['o'],
                                                       pre_seek=(0, 0),
                                                       pre_truncate=True,
                                                       pre_flush=True,
                                                       after_seek=(master_obj.__class__.CACHE_INFO, 0),
                                                       after_flush=True)

        else:
            raise DecodeError

    except DecodeError:
        # Handle decoding error
        if decoder is not None:
            record['o'] = decoder()
        if isinstance(record['o'], io.BufferedRandom):
            record['size'] = os.path.getsize(record['o'].name)
        else:
            record['size'] = len(record['o']) + master_obj.CACHE_INFO

        f = record['o'] = write_to_cached_file(record['size'],
                                               record['frameRate'],
                                               record['sampleFormat'] if record['sampleFormat'] else 0,
                                               record['nchannels'],
                                               file_name=path,
                                               data=record['o'],
                                               pre_seek=(0, 0),
                                               pre_truncate=True,
                                               pre_flush=True,
                                               after_seek=(master_obj.__class__.CACHE_INFO, 0),
                                               after_flush=True)

    record['duration'] = record['size'] / (record['frameRate'] *
                                           record['nchannels'] *
                                           Audio.get_sample_size(record['sampleFormat']))
    if isinstance(record, pd.Series):
        # Extract name information from file path for Series
        post = record['o'].name.index(master_obj.__class__.BUFFER_TYPE)
        pre = max(record['o'].name.rfind('\\'), record['o'].name.rfind('/'))
        pre = (pre + 1) if pre > 0 else 0
        record.name = record['o'].name[pre: post]

    return record

