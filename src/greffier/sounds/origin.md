# Where these sounds come from

`web-search.wav`, Kenney, *Interface Sounds* (1.0), file `maximize_002.wav`,
**CC0**: free for personal, educational and commercial use, crediting optional.
<https://kenney.nl/assets/interface-sounds>

Chosen by measurement rather than by ear, among thirty of that pack: 0.26 s, a
248 ms attack, so no click, and its energy centred at 3.5 kHz, above most of
what a voice carries, which is what makes it audible in a meeting without
masking anybody. Brought down by **18 dB** from the original, which peaked at
-1 dB: a cue has no business sitting at the level of the people talking.

    ffmpeg -i maximize_002.wav -af volume=-18dB -ar 44100 -ac 1 -c:a pcm_s16le web-search.wav

`heard.wav`, same pack, file `drop_002.wav`, **CC0**. Chosen for the opposite
reason to the other one: it fires on every sentence spoken to her, so it had to
be the one nobody notices twice, 0.20 s, centred at 910 Hz, low and round
rather than sharp. Brought down **20 dB**, two more than the search cue, for the
same reason.

    ffmpeg -i drop_002.wav -af volume=-20dB -ar 44100 -ac 1 -c:a pcm_s16le heard.wav
