// The camera on a video call, watched with plain rules, no model: a picture goes to the server only when the view has
// changed enough from the last one sent. Five times a second the frame is drawn 64x48 in grey and compared with that
// last picture: the share of pixels that moved (brightness and contrast of the whole frame evened out first, so a light
// going on or the camera's exposure is not a change; the middle of the frame counts double the edges). Once the change is big, the
// picture is taken when the view has settled (a thing put down, held up still), or anyway after a while of it still
// moving (a big action going on). Never two pictures closer than the cool-down. The first look goes out once the camera
// has warmed up, so the server knows the scene before anything changes in it.
(function () {
  'use strict';
  const W = 64, H = 48, STEP_MS = 200, SPREAD = 40;
  const RULES = {
    pixel: 28,          // a pixel moved: this much brighter or darker than in the other frame (0-255), after the mean
    change: 0.04,       // the view has changed: this share of the (weighted) frame moved since the last picture (a mug
                        // put on the desk is about 0.05; a 1 px camera shake and a light going on stay at 0)
    still: 0.02,        // ... and it has settled: frame to frame, less than this share moving
    settle_ms: 400,     // for this long
    moving_ms: 2500,    // or it has been changing this long without settling: taken anyway
    cooldown_ms: 3000,  // never two pictures closer than this
    first_ms: 1200,     // the first look, after the camera warms up
    width: 640, quality: 0.7,
  };
  const weight = new Float32Array(W * H);
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
    const mid = x > W / 4 && x < W * 3 / 4 && y > H / 4 && y < H * 3 / 4;
    weight[y * W + x] = mid ? 2 : 1;
  }
  const total = weight.reduce((a, b) => a + b, 0);

  function grey(ctx, video) {
    ctx.drawImage(video, 0, 0, W, H);
    const px = ctx.getImageData(0, 0, W, H).data, g = new Float32Array(W * H);
    let sum = 0;
    for (let i = 0; i < W * H; i++) { g[i] = 0.299 * px[i * 4] + 0.587 * px[i * 4 + 1] + 0.114 * px[i * 4 + 2]; sum += g[i]; }
    const mean = sum / (W * H);
    let sq = 0;
    for (let i = 0; i < W * H; i++) { g[i] -= mean; sq += g[i] * g[i]; }
    const k = SPREAD / Math.max(8, Math.sqrt(sq / (W * H)));      // the same contrast whatever the light (an empty dark frame is not blown up)
    for (let i = 0; i < W * H; i++) g[i] *= k;
    return g;
  }
  function moved(a, b) {
    let m = 0;
    for (let i = 0; i < a.length; i++) if (Math.abs(a[i] - b[i]) > RULES.pixel) m += weight[i];
    return m / total;
  }

  // start(video, onPicture): onPicture({image: base64 JPEG, change, first}) each time a picture is taken; returns stop()
  function start(video, onPicture) {
    const small = document.createElement('canvas'); small.width = W; small.height = H;
    const sctx = small.getContext('2d', { willReadFrequently: true });
    const big = document.createElement('canvas');
    let ref = null, prev = null, changingSince = 0, stillSince = 0, lastAt = 0;
    const began = performance.now();
    function take(g, change, first) {
      const w = Math.min(RULES.width, video.videoWidth), h = Math.round(w * video.videoHeight / video.videoWidth);
      big.width = w; big.height = h; big.getContext('2d').drawImage(video, 0, 0, w, h);
      const image = big.toDataURL('image/jpeg', RULES.quality).split(',')[1];
      ref = g; changingSince = stillSince = 0; lastAt = performance.now();
      onPicture({ image, change: Math.round(change * 1000) / 1000, first });
    }
    const timer = setInterval(() => {
      if (!video.videoWidth || video.readyState < 2) return;
      const now = performance.now(), g = grey(sctx, video);
      const motion = prev ? moved(g, prev) : 1; prev = g;
      if (!ref) { if (now - began >= RULES.first_ms) take(g, 0, true); return; }
      const change = moved(g, ref);
      api.last = { change, motion };                          // for tuning RULES from the console
      if (change < RULES.change) { changingSince = stillSince = 0; return; }
      if (!changingSince) changingSince = now;
      stillSince = motion < RULES.still ? (stillSince || now) : 0;
      if (now - lastAt < RULES.cooldown_ms) return;
      if ((stillSince && now - stillSince >= RULES.settle_ms) || now - changingSince >= RULES.moving_ms) take(g, change, false);
    }, STEP_MS);
    return () => clearInterval(timer);
  }

  const api = { start, RULES, last: null };
  window.JevWatch = api;
})();
