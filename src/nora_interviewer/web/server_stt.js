class NoraLinearResampler {
  constructor(inputRate, outputRate) {
    if (!(inputRate > 0) || !(outputRate > 0)) {
      throw new Error("Invalid audio sample rate");
    }
    this.inputRate = inputRate;
    this.outputRate = outputRate;
    this.ratio = inputRate / outputRate;
    this.buffer = new Float32Array(0);
    this.position = 0;
  }

  push(input) {
    if (!(input instanceof Float32Array) || input.length === 0) {
      return new Float32Array(0);
    }
    if (this.inputRate === this.outputRate) {
      return input.slice();
    }

    const data = new Float32Array(
      this.buffer.length + input.length
    );
    data.set(this.buffer, 0);
    data.set(input, this.buffer.length);

    const output = [];
    while (this.position + 1 < data.length) {
      const leftIndex = Math.floor(this.position);
      const fraction = this.position - leftIndex;
      const left = data[leftIndex];
      const right = data[leftIndex + 1];
      output.push(
        left + (right - left) * fraction
      );
      this.position += this.ratio;
    }

    const consumed = Math.floor(this.position);
    this.buffer = data.slice(consumed);
    this.position -= consumed;
    return Float32Array.from(output);
  }
}


class NoraServerSttClient {
  constructor({
    sessionId,
    locale,
    config,
    onState = () => {},
    onPartial = () => {},
    onFinal = () => {},
    onError = () => {},
  }) {
    this.sessionId = sessionId;
    this.locale = locale || "en";
    this.config = config || {
      encoding: "pcm16",
      sample_rate_hz: 16000,
      channels: 1,
      max_chunk_bytes: 32768,
      max_buffered_bytes: 524288,
    };
    this.onState = onState;
    this.onPartial = onPartial;
    this.onFinal = onFinal;
    this.onError = onError;

    this.ws = null;
    this.connectPromise = null;
    this.openPromise = null;
    this.openResolve = null;
    this.openReject = null;

    this.streamId = null;
    this.reconnectToken = null;
    this.generation = 0;
    this.nextSequence = 0;
    this.serverNextSequence = 0;
    this.pendingAcks = 0;
    this.frameQueue = [];
    this.maxInFlight = 6;
    this.maxSocketBufferedBytes = 128 * 1024;

    this.mediaStream = null;
    this.audioContext = null;
    this.sourceNode = null;
    this.captureNode = null;
    this.silentGain = null;
    this.workletUrl = null;
    this.resampler = null;
    this.pendingPcm = new Int16Array(0);

    this.active = false;
    this.committing = false;
    this.intentionalClose = false;
  }

  isRecording() {
    return this.active && !this.committing;
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
          + "/v1/ws/audio/" + this.sessionId
        );

        ws.onopen = () => {
          this.ws = ws;
          this.connectPromise = null;
          resolve(ws);
        };
        ws.onerror = () => {
          this.connectPromise = null;
          reject(
            new Error("Server STT connection failed")
          );
        };
        ws.onclose = () => {
          if (this.ws === ws) {
            this.ws = null;
          }
          this.connectPromise = null;
          if (
            !this.intentionalClose
            && (this.active || this.committing)
          ) {
            this.fail(
              new Error(
                "Server STT connection closed unexpectedly"
              )
            );
          }
        };
        ws.onmessage = (event) => {
          this.handleMessage(event);
        };
      }
    );
    return this.connectPromise;
  }

  async start() {
    if (this.active || this.committing) {
      return;
    }
    if (this.config.encoding !== "pcm16") {
      throw new Error(
        "Browser server STT currently requires pcm16"
      );
    }
    if (this.config.channels !== 1) {
      throw new Error(
        "Browser server STT currently requires mono audio"
      );
    }

    await this.ensureSocket();
    await this.openStream();

    try {
      await this.startCapture();
    } catch (error) {
      await this.cancel("microphone_start_failed");
      throw error;
    }

    this.active = true;
    this.onState({
      phase: "listening",
      transport: "server-stt",
    });
  }

  async openStream() {
    if (
      !this.ws
      || this.ws.readyState !== WebSocket.OPEN
    ) {
      throw new Error("Server STT socket is not connected");
    }

    this.openPromise = new Promise(
      (resolve, reject) => {
        this.openResolve = resolve;
        this.openReject = reject;
      }
    );

    this.ws.send(JSON.stringify({
      type: "open",
      data: {
        locale: this.locale,
        config: this.config,
      },
    }));

    const timeout = setTimeout(() => {
      if (this.openReject) {
        this.openReject(
          new Error("Server STT open timed out")
        );
      }
      this.clearOpenPromise();
    }, 10000);

    try {
      await this.openPromise;
    } finally {
      clearTimeout(timeout);
    }
  }

  clearOpenPromise() {
    this.openPromise = null;
    this.openResolve = null;
    this.openReject = null;
  }

  async startCapture() {
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error(
        "Microphone capture is not supported by this browser"
      );
    }

    this.mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });

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
    await this.audioContext.resume();
    this.resampler = new NoraLinearResampler(
      this.audioContext.sampleRate,
      this.config.sample_rate_hz,
    );
    this.pendingPcm = new Int16Array(0);

    this.sourceNode = (
      this.audioContext
      .createMediaStreamSource(this.mediaStream)
    );
    this.silentGain = this.audioContext.createGain();
    this.silentGain.gain.value = 0;
    this.silentGain.connect(
      this.audioContext.destination
    );

    if (
      this.audioContext.audioWorklet
      && window.AudioWorkletNode
    ) {
      const code = `
        class NoraPcmCaptureProcessor extends AudioWorkletProcessor {
          process(inputs) {
            const input = inputs[0];
            if (input && input[0] && input[0].length) {
              this.port.postMessage(input[0].slice());
            }
            return true;
          }
        }
        registerProcessor(
          "nora-pcm-capture",
          NoraPcmCaptureProcessor
        );
      `;
      const blob = new Blob(
        [code],
        {type: "application/javascript"},
      );
      this.workletUrl = URL.createObjectURL(blob);
      await this.audioContext.audioWorklet.addModule(
        this.workletUrl
      );
      URL.revokeObjectURL(this.workletUrl);
      this.workletUrl = null;

      this.captureNode = new AudioWorkletNode(
        this.audioContext,
        "nora-pcm-capture",
        {
          numberOfInputs: 1,
          numberOfOutputs: 1,
          outputChannelCount: [1],
        },
      );
      this.captureNode.port.onmessage = (event) => {
        const samples = (
          event.data instanceof Float32Array
          ? event.data
          : new Float32Array(event.data)
        );
        this.handleSamples(samples);
      };
    } else {
      this.captureNode = (
        this.audioContext.createScriptProcessor(
          2048,
          1,
          1,
        )
      );
      this.captureNode.onaudioprocess = (event) => {
        const samples = (
          event.inputBuffer
          .getChannelData(0)
          .slice()
        );
        this.handleSamples(samples);
      };
    }

    this.sourceNode.connect(this.captureNode);
    this.captureNode.connect(this.silentGain);
  }

  handleSamples(samples) {
    if (!this.active && !this.openPromise) {
      return;
    }
    if (!this.resampler) return;

    const resampled = this.resampler.push(samples);
    if (!resampled.length) return;

    const pcm = new Int16Array(resampled.length);
    for (let i = 0; i < resampled.length; i += 1) {
      const sample = Math.max(
        -1,
        Math.min(1, resampled[i]),
      );
      pcm[i] = (
        sample < 0
        ? Math.round(sample * 32768)
        : Math.round(sample * 32767)
      );
    }

    const combined = new Int16Array(
      this.pendingPcm.length + pcm.length
    );
    combined.set(this.pendingPcm, 0);
    combined.set(pcm, this.pendingPcm.length);
    this.pendingPcm = combined;

    const frameSamples = Math.max(
      160,
      Math.round(
        this.config.sample_rate_hz * 0.02
      ),
    );

    while (this.pendingPcm.length >= frameSamples) {
      const frame = this.pendingPcm.slice(
        0,
        frameSamples,
      );
      this.pendingPcm = this.pendingPcm.slice(
        frameSamples
      );
      this.frameQueue.push(frame);
    }
    this.flushFrames();
  }

  flushFrames() {
    if (
      !this.ws
      || this.ws.readyState !== WebSocket.OPEN
      || !this.streamId
    ) {
      return;
    }

    while (
      this.frameQueue.length
      && this.pendingAcks < this.maxInFlight
      && this.ws.bufferedAmount
        < this.maxSocketBufferedBytes
    ) {
      const frame = this.frameQueue.shift();
      const sequence = this.nextSequence;
      this.nextSequence += 1;
      this.pendingAcks += 1;

      this.ws.send(JSON.stringify({
        type: "chunk",
        data: {
          sequence,
          generation: this.generation,
          audio_base64: this.pcmToBase64(frame),
        },
      }));
    }
  }

  pcmToBase64(frame) {
    const bytes = new Uint8Array(frame.buffer);
    let binary = "";
    for (let i = 0; i < bytes.length; i += 1) {
      binary += String.fromCharCode(bytes[i]);
    }
    return btoa(binary);
  }

  async stop() {
    if (!this.active || this.committing) {
      return;
    }

    this.active = false;
    this.committing = true;
    await this.stopCapture();

    if (this.pendingPcm.length) {
      this.frameQueue.push(
        this.pendingPcm.slice()
      );
      this.pendingPcm = new Int16Array(0);
      this.flushFrames();
    }

    try {
      await this.waitForDrain(3000);
    } catch (error) {
      await this.cancel("audio_drain_timeout");
      throw error;
    }

    if (
      !this.ws
      || this.ws.readyState !== WebSocket.OPEN
      || !this.streamId
    ) {
      await this.cancel("stt_socket_unavailable");
      throw new Error(
        "Server STT connection is unavailable"
      );
    }

    this.ws.send(JSON.stringify({
      type: "commit",
      data: {
        stream_id: this.streamId,
      },
    }));
    this.onState({
      phase: "processing",
      transport: "server-stt",
    });
  }

  async waitForDrain(timeoutMs) {
    const started = performance.now();
    while (
      this.frameQueue.length
      || this.pendingAcks
    ) {
      this.flushFrames();
      if (
        performance.now() - started
        >= timeoutMs
      ) {
        throw new Error(
          "Timed out waiting for microphone audio acknowledgements"
        );
      }
      await new Promise(
        (resolve) => setTimeout(resolve, 20)
      );
    }
  }

  async stopCapture() {
    if (this.captureNode) {
      try {
        this.captureNode.disconnect();
      } catch {}
      this.captureNode.onaudioprocess = null;
      if (this.captureNode.port) {
        this.captureNode.port.onmessage = null;
      }
      this.captureNode = null;
    }

    if (this.sourceNode) {
      try {
        this.sourceNode.disconnect();
      } catch {}
      this.sourceNode = null;
    }

    if (this.silentGain) {
      try {
        this.silentGain.disconnect();
      } catch {}
      this.silentGain = null;
    }

    if (this.mediaStream) {
      for (const track of this.mediaStream.getTracks()) {
        track.stop();
      }
      this.mediaStream = null;
    }

    if (this.audioContext) {
      try {
        await this.audioContext.close();
      } catch {}
      this.audioContext = null;
    }
    this.resampler = null;

    if (this.workletUrl) {
      URL.revokeObjectURL(this.workletUrl);
      this.workletUrl = null;
    }
  }

  handleMessage(event) {
    if (typeof event.data !== "string") {
      this.fail(
        new Error(
          "Server STT returned unexpected binary data"
        )
      );
      return;
    }

    let packet;
    try {
      packet = JSON.parse(event.data);
    } catch {
      this.fail(
        new Error("Server STT returned invalid JSON")
      );
      return;
    }

    if (packet.type === "stream_opened") {
      this.streamId = (
        packet.data?.state?.stream_id
        || null
      );
      this.reconnectToken = (
        packet.data?.reconnect_token
        || null
      );
      this.generation = (
        packet.data?.state?.generation
        || 0
      );
      this.nextSequence = (
        packet.data?.state?.next_sequence
        || 0
      );
      this.serverNextSequence = this.nextSequence;
      this.pendingAcks = 0;
      this.frameQueue = [];

      const resolve = this.openResolve;
      this.clearOpenPromise();
      resolve?.(packet.data);
      return;
    }

    if (packet.type === "chunk_ack") {
      this.pendingAcks = Math.max(
        0,
        this.pendingAcks - 1,
      );
      this.serverNextSequence = (
        packet.data?.next_sequence
        ?? this.serverNextSequence
      );
      this.flushFrames();
      return;
    }

    if (packet.type === "stream_committed") {
      this.onState({
        phase: "processing",
        transport: "server-stt",
      });
      return;
    }

    if (packet.type === "transcript_partial") {
      this.onPartial(packet.data || {});
      return;
    }

    if (packet.type === "transcript_final") {
      const payload = packet.data || {};
      this.committing = false;
      this.active = false;
      this.onState({
        phase: "idle",
        transport: "server-stt",
      });
      this.onFinal(payload);

      if (
        this.ws
        && this.ws.readyState === WebSocket.OPEN
        && this.streamId
      ) {
        this.ws.send(JSON.stringify({
          type: "close",
          data: {
            stream_id: this.streamId,
            cancel_provider: false,
          },
        }));
      }
      return;
    }

    if (packet.type === "stream_closed") {
      this.resetStreamState();
      return;
    }

    if (packet.type === "error") {
      const message = (
        packet.error?.message
        || packet.error
        || "Server STT error"
      );
      if (this.openReject) {
        const reject = this.openReject;
        this.clearOpenPromise();
        reject(new Error(message));
        return;
      }
      this.fail(new Error(message));
    }
  }

  resetStreamState() {
    this.streamId = null;
    this.reconnectToken = null;
    this.generation = 0;
    this.nextSequence = 0;
    this.serverNextSequence = 0;
    this.pendingAcks = 0;
    this.frameQueue = [];
    this.pendingPcm = new Int16Array(0);
  }

  async cancel(reason = "client_cancelled") {
    this.active = false;
    this.committing = false;
    await this.stopCapture();

    if (
      this.ws
      && this.ws.readyState === WebSocket.OPEN
      && this.streamId
    ) {
      this.ws.send(JSON.stringify({
        type: "close",
        data: {
          stream_id: this.streamId,
          cancel_provider: true,
          reason,
        },
      }));
    }
    this.resetStreamState();
    this.onState({
      phase: "idle",
      reason,
      transport: "server-stt",
    });
  }

  async close() {
    this.intentionalClose = true;
    await this.cancel("voice_disabled");
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    this.intentionalClose = false;
  }

  fail(error) {
    const wasActive = this.active || this.committing;
    this.active = false;
    this.committing = false;
    this.stopCapture().catch(() => {});
    this.resetStreamState();
    if (wasActive) {
      this.onState({
        phase: "idle",
        transport: "server-stt",
      });
    }
    this.onError(error);
  }
}

window.NoraServerSttClient = NoraServerSttClient;
