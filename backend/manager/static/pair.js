"use strict";
document.getElementById("pair-form").addEventListener("submit", async event => {
  event.preventDefault();
  const form = event.currentTarget, button = form.querySelector("button"), error = document.getElementById("pair-error");
  button.disabled = true; error.hidden = true;
  const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch("/api/access/pair", {method:"POST", signal:controller.signal,
      headers:{"Content-Type":"application/json", "X-Novel-Helper":"1"}, body:JSON.stringify(Object.fromEntries(new FormData(form)))});
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "请输入 8 位配对码");
    location.replace("/");
  } catch (reason) {
    error.textContent = reason.name === "AbortError" ? "连接超时，请确认电脑在线" : reason.message;
    error.hidden = false;
  } finally {clearTimeout(timer); button.disabled = false;}
});
