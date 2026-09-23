class NoraServerTtsPlayer {
  constructor({
    sessionId,
    locale,
    config,
    onState = () => {},
    onError = () => {},
  }) {
    this.sessionId = sessionId;
    this.locale = locale;
    this.config = config || {
      encoding: "pcm16",
      sample_rate_hz: 24000,
      channels: 1,
    };
    this.onState = onState;
    this.onError = onError;

    this.ws = null;
    this.connectPromise = null;
    this.audioContext = null;
    this.playhead = 0;
    this.sources = new Set();
    this.pendingChunk = null;
    this.activeStreamId = null;
    this.activeTurnId = null;
    this.providerDone = false;
    this.receivedAudio = false;
  }

  async enable() {
    this.ensureAudioContext();
    await this.audioContext.resume();
    await this.ensureSocket();
  }

  ensureAudioContext() {
    if (this.audioContext) return this.audioContext;
    const AudioContextClass = (
      window.AudioContext
      || window.webkitAudioContext
    );
    if (!AudioContextClass) {
      throw new Error(
        "Web Audio is not supported by this browser"
      );
    }
    this.audioContext = new AudioContextClass();
    this.playhead = this.audioContext.currentTime;
    return this.audioContext;
  }

  async ensureSocket() {
    if (
      this.ws
      && this.ws.readyState === WebSocket.OPEN
    ) {
      return this.ws;
    }
    if (this.connectPromise) {
      return this.connectPromise;
    }

    const scheme = (
      location.protocol === "https:"
      ? "wss"
      : "ws"
    );
    this.connectPromise = new Promise(
      (resolve, reject) => {
        const ws = new WebSocket(
          scheme + "://" + location.host
          + "/v1/ws/tts/" + this.sessionId
        );
        ws.binaryType = "arraybuffer";

        ws.onopen = () => {
          this.ws = ws;
          this.connectPromise = null;
          resolve(ws);
        };
        ws.onerror = () => {
          this.connectPromise = null;
          reject(
            new Error("Server TTS connection failed")
          );
        };
        ws.onclose = () => {
          if (this.ws === ws) {
            this.ws = null;
          }
          this.connectPromise = null;
        };
        ws.onmessage = (event) => {
          this.handleMessage(event);
        };
      }
    );
    return this.connectPromise;
  }

  async playTurn(turn) {
    if (!turn?.id || !turn?.text) return;
    await this.enable();

    if (
      this.activeStreamId
      || this.sources.size
    ) {
      await this.cancel("superseded");
    }

    this.activeTurnId = turn.id;
    this.providerDone = false;
    this.receivedAudio = false;
    this.pendingChunk = null;
    this.playhead = Math.max(
      this.audioContext.currentTime + 0.02,
      this.playhead,
    );

    this.ws.send(JSON.stringify({
      type: "open",
      data: {
        turn_id: turn.id,
        locale: this.locale,
        config: this.config,
      },
    }));
  }

  handleMessage(event) {
    if (typeof event.data !== "string") {
      this.handleBinary(event.data);
      return;
    }

    let packet;
    try {
      packet = JSON.parse(event.data);
    } catch {
      this.fail(
        new Error("Server TTS returned invalid JSON")
      );
      return;
    }

    if (packet.type === "stream_opened") {
      this.activeStreamId = (
        packet.data?.state?.stream_id
        || null
      );
      this.activeTurnId = (
        packet.data?.state?.turn_id
        || this.activeTurnId
      );
      this.onState({
        phase: "speaking",
        turnId: this.activeTurnId,
      });
      return;
    }

    if (packet.type === "audio_chunk") {
      this.pendingChunk = packet.data || null;
      return;
    }

    if (
      packet.type === "stream_completed"
      || packet.type === "stream_cancelled"
    ) {
      this.providerDone = true;
      this.activeStreamId = null;
      if (
        packet.type === "stream_cancelled"
      ) {
        this.stopLocalPlayback();
      }
      this.finishIfDrained();
      return;
    }

    if (packet.type === "error") {
      const message = (
        packet.error?.message
        || packet.error
        || "Server TTS error"
      );
      this.fail(new Error(message));
    }
  }

  handleBinary(data) {
    if (!(data instanceof ArrayBuffer)) {
      return;
    }
    const meta = this.pendingChunk;
    this.pendingChunk = null;
    if (!meta) {
      this.fail(
        new Error(
          "Server TTS audio arrived without metadata"
        )
      );
      return;
    }
    if (
      meta.turn_id
      && this.activeTurnId
      && meta.turn_id !== this.activeTurnId
    ) {
      return;
    }
    this.receivedAudio = true;
    this.queuePcm16(data);
  }

  queuePcm16(arrayBuffer) {
    if (this.config.encoding !== "pcm16") {
      this.fail(
        new Error(
          "Unsupported browser TTS encoding: "
          + this.config.encoding
        )
      );
      return;
    }

    const context = this.ensureAudioContext();
    const channels = this.config.channels || 1;
    const sampleRate = (
      this.config.sample_rate_hz
      || 24000
    );
    const sampleCount = Math.floor(
      arrayBuffer.byteLength / 2
    );
    const frameCount = Math.floor(
      sampleCount / channels
    );
    if (!frameCount) return;

    const audioBuffer = context.createBuffer(
      channels,
      frameCount,
      sampleRate,
    );
    const view = new DataView(arrayBuffer);

    for (
      let channel = 0;
      channel < channels;
      channel += 1
    ) {
      const target = audioBuffer.getChannelData(
        channel
      );
      for (
        let frame = 0;
        frame < frameCount;
        frame += 1
      ) {
        const sampleIndex = (
          frame * channels + channel
        );
        target[frame] = (
          view.getInt16(
            sampleIndex * 2,
            true,
          )
          / 32768
        );
      }
    }

    const source = context.createBufferSource();
    source.buffer = audioBuffer;
    source.connect(context.destination);

    const startAt = Math.max(
      context.currentTime + 0.01,
      this.playhead,
    );
    this.playhead = (
      startAt + audioBuffer.duration
    );
    this.sources.add(source);
    source.onended = () => {
      this.sources.delete(source);
      this.finishIfDrained();
    };
    source.start(startAt);
  }

  finishIfDrained() {
    if (
      !this.providerDone
      || this.sources.size
    ) {
      return;
    }
    const turnId = this.activeTurnId;
    this.activeTurnId = null;
    this.pendingChunk = null;
    this.onState({
      phase: "idle",
      turnId,
    });
  }

  stopLocalPlayback() {
    for (const source of this.sources) {
      try {
        source.stop();
      } catch {
        // Already stopped.
      }
    }
    this.sources.clear();
    if (this.audioContext) {
      this.playhead = (
        this.audioContext.currentTime
      );
    }
  }

  async cancel(reason = "client_cancelled") {
    this.stopLocalPlayback();
    if (
      this.ws
      && this.ws.readyState === WebSocket.OPEN
      && this.activeStreamId
    ) {
      this.ws.send(JSON.stringify({
        type: "cancel",
        data: {reason},
      }));
    }
    this.activeStreamId = null;
    this.activeTurnId = null;
    this.pendingChunk = null;
    this.providerDone = true;
    this.onState({
      phase: "idle",
      reason,
    });
  }

  async close() {
    await this.cancel("voice_disabled");
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    if (this.audioContext) {
      await this.audioContext.close();
      this.audioContext = null;
    }
  }

  fail(error) {
    const hadAudio = this.receivedAudio;
    this.stopLocalPlayback();
    this.activeStreamId = null;
    this.pendingChunk = null;
    this.providerDone = true;
    this.onError(error, {hadAudio});
  }
}

window.NoraServerTtsPlayer = NoraServerTtsPlayer;
