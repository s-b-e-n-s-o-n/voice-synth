#!/usr/bin/env bash
set -e
cd /tmp
curl -sL https://github.com/s-b-e-n-s-o-n/voice-synth/archive/main.tar.gz | tar xz
cd voice-synth-main
./voice-synth
