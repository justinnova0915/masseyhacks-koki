# Raspberry Pi `arecord` Troubleshooting Summary

## Problem:

The user encountered an error when trying to use `arecord` on a Raspberry Pi:

```
ALSA lib pcm_pulse.c:758:(pulse_prepare) PulseAudio: Unable to create stream: Timeout
arecord: set_params:1416: Unable to install hw params:
ACCESS:  RW_INTERLEAVED
FORMAT:  S16_LE
SUBFORMAT:  STD
SAMPLE_BITS: 16
FRAME_BITS: 32
CHANNELS: 2
RATE: 44100
PERIOD_TIME: 125000
PERIOD_SIZE: (5512 5513)
PERIOD_BYTES: 22050
PERIODS: 4
BUFFER_TIME: 500000
BUFFER_SIZE: 22050
BUFFER_BYTES: 88200
TICK_TIME: [0 0]
```

## Diagnosis Steps & Findings:

1. **Initial System Checks:**

   * `pulseaudio --check` indicated: `PulseAudio not running or error`.
   * `pactl info | grep "Server Name"` showed: `Server Name: PulseAudio (on PipeWire 1.2.7)`. This meant PipeWire was managing the PulseAudio interface.
   * `pactl list short sources` (listing PulseAudio/PipeWire inputs) initially only showed `auto_null.monitor` and did *not* list the "AB13X USB Audio" microphone.
   * `arecord -l` (listing ALSA hardware devices) *did* show the "AB13X USB Audio" microphone (as `card 0, device 0`).
   * **Conclusion:** The underlying ALSA system recognized the microphone, but PipeWire (acting as the PulseAudio server) was not making it available as an input source.
2. **Direct ALSA Test:**

   * A direct ALSA recording test was performed: `arecord -D hw:0,0 -d 5 -f S16_LE -r 44100 -c 2 -t wav test_audio_alsa.wav`.
   * This command **succeeded**.
   * **Conclusion:** This confirmed the microphone hardware and basic ALSA drivers were functioning correctly. The issue was specifically with PipeWire's handling of the device.

## Resolution:

1. **Restarting PipeWire Services:**

   * The following commands were executed to restart the relevant user-level PipeWire services:
     ```bash
     systemctl --user restart pipewire.service pipewire-pulse.socket pipewire-pulse.service
     systemctl --user restart wireplumber.service
     ```
2. **Verification:**

   * After restarting the services, `pactl list short sources` **then showed the USB microphone** (`alsa_input.usb-Generic_AB13X_USB_Audio...`) as an available input source for PipeWire/PulseAudio.
   * The original `arecord` command (e.g., `arecord -d 5 -f cd -t wav test_audio_pipewire.wav`), which relies on the default PulseAudio/PipeWire interface, **then succeeded**.

## Summary of Root Cause:

The `arecord` failure was due to the PipeWire audio service not correctly detecting or initializing the USB microphone as an available input source. Restarting the PipeWire services forced them to re-scan and properly recognize the microphone, allowing `arecord` (and other applications relying on PulseAudio/PipeWire) to use it successfully.

scp C:\Users\justi\PycharmProjects\Kokoro\raspiScripts\rpi_audio_client.py justinli@192.168.2.125:/home/justinli/Documents/koki_client

sudo fuser -v /dev/snd/pcmC0D0p

cvlc udp://@:1234 --network-caching=100 --fullscreen --no-video-title-show
