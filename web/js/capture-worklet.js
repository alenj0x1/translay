// Captura el audio que suena en el video, lo mezcla a mono y lo baja a 16 kHz.
// Envía bloques Int16 de `chunk` muestras (100 ms por defecto) al hilo principal.
class Capture extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const o = options.processorOptions || {};
    this.ratio = sampleRate / (o.target || 16000);
    this.out = new Int16Array(o.chunk || 1600);
    this.n = 0;
    this.acc = 0;
    this.sum = 0;
    this.cnt = 0;
  }

  process(inputs) {
    const ch = inputs[0];
    if (!ch || ch.length === 0) return true;
    const L = ch[0];
    const R = ch[1] || L;
    for (let i = 0; i < L.length; i++) {
      // filtro de caja + diezmado: suficiente para voz a 16 kHz
      this.sum += (L[i] + R[i]) * 0.5;
      this.cnt++;
      this.acc += 1;
      if (this.acc >= this.ratio) {
        this.acc -= this.ratio;
        const v = Math.max(-1, Math.min(1, this.sum / this.cnt));
        this.sum = 0;
        this.cnt = 0;
        this.out[this.n++] = v * 32767;
        if (this.n === this.out.length) {
          this.port.postMessage(this.out.slice(0));
          this.n = 0;
        }
      }
    }
    return true;
  }
}

registerProcessor("capture", Capture);
