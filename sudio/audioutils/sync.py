import numpy as np
import samplerate

from sudio.types import SampleFormat
from sudio.audioutils.audio import Audio
from sudio.audioutils.channel import shuffle2d_channels


def synchronize_audio(rec,
                      nchannels: int,
                      sample_rate: int,
                      sample_format_id: int,
                      output_data='byte') -> dict:
    """
    Synchronizes audio data with the specified parameters.

    Parameters:
    - rec (dict): The input audio recording data.
    - nchannels (int): The desired number of channels.
    - sample_rate (int): The desired sample rate.
    - sample_format_id (int): The desired sample format ID.
    - output_data (str): Output data format, can be 'byte' or 'ndarray'.

    Returns:
    - dict: The synchronized audio recording data.

    Notes:
    - This function performs channel adjustment, resampling, and sample format conversion.
    - The input `rec` dictionary is modified in-place.

    Usage:
    ```python
    new_rec = synchronize_audio(rec, nchannels=2, sample_rate=44100, sample_format_id=SampleFormat.formatInt16.value)
    ```

    :param rec: The input audio recording data.
    :param nchannels: The desired number of channels.
    :param sample_rate: The desired sample rate.
    :param sample_format_id: The desired sample format ID.
    :param output_data: Output data format, can be 'byte' or 'ndarray'.
    :return: The synchronized audio recording data.
    """

    form = Audio.get_sample_size(rec['sampleFormat'])
    if rec['sampleFormat'] == SampleFormat.formatFloat32.value:
        form = '<f{}'.format(form)
    else:
        form = '<i{}'.format(form)
    data = np.frombuffer(rec['o'], form)
    if rec['nchannels'] == 1:
        if nchannels > rec['nchannels']:
            data = np.vstack([data for i in range(nchannels)])
            rec['nchannels'] = nchannels

    # elif nchannels == 1 or _mono_mode:
    #     data = np.mean(data.reshape(int(data.shape[-1:][0] / rec['nchannels']),
    #                                 rec['nchannels']),
    #                    axis=1)
    else:
        data = [[data[i::rec['nchannels']]] for i in range(nchannels)]
        data = np.append(*data, axis=0)

    if not sample_rate == rec['frameRate']:
        scale = sample_rate / rec['frameRate']

        # firwin = scisig.firwin(23, fc)
        # firdn = lambda firwin, data,  scale: samplerate.resample(data, )
        if len(data.shape) == 1:
            # mono
            data = samplerate.resample(data, scale, converter_type='sinc_fastest')
        else:
            # multi channel
            res = samplerate.resample(data[0], scale, converter_type='sinc_fastest')
            for i in data[1:]:
                res = np.vstack((res,
                                 samplerate.resample(i, scale, converter_type='sinc_fastest')))
            data = res

    if output_data.startswith('b') and rec['nchannels'] > 1:
        data = shuffle2d_channels(data)

    rec['nchannels'] = nchannels
    rec['sampleFormat'] = sample_format_id

    form = Audio.get_sample_size(sample_format_id)
    if sample_format_id == SampleFormat.formatFloat32.value:
        form = '<f{}'.format(form)
    else:
        form = '<i{}'.format(form)

    if output_data.startswith('b'):
        rec['o'] = data.astype(form).tobytes()
    else:
        rec['o'] = data.astype(form)

    rec['size'] = len(rec['o'])
    rec['frameRate'] = sample_rate

    rec['duration'] = rec['size'] / (rec['frameRate'] *
                                     rec['nchannels'] *
                                     Audio.get_sample_size(rec['sampleFormat']))

    return rec