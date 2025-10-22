(function () {
  const input = document.querySelector("#id_password1") || document.querySelector("#id_new_password1");
  if (!input) return;
  const meter = document.getElementById("meter");
  const meterText = document.getElementById("meter-text");

  function score(pw) {
    let s = 0;
    if (!pw) return 0;
    if (pw.length >= 12) s++;
    if (/[A-Z]/.test(pw)) s++;
    if (/[a-z]/.test(pw)) s++;
    if (/\d/.test(pw)) s++;
    if (/[!@#$%^&*()\-_=+\[\]{};:'",.<>/?\\|`~]/.test(pw)) s++;
    return Math.min(4, s);
  }
  function label(v) { return ["Very weak","Weak","Okay","Good","Strong"][v] || "—"; }
  function update() {
    const v = score(input.value);
    if (meter) meter.value = v;
    if (meterText) meterText.textContent = label(v);
  }
  input.addEventListener("input", update);
  update();
})();