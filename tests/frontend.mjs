// Exercises the shipped JS and real local API in an isolated DOM, without operating the user's browser.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { Window } from "happy-dom";

const origin = process.env.AMT_TEST_URL || "http://127.0.0.1:4321";
const window = new Window({
  url: origin,
  settings: { disableJavaScriptFileLoading: true, disableCSSFileLoading: true },
});
const errors = [];
window.addEventListener("error", (e) => errors.push(e.message));
window.fetch = (url, options) => fetch(new URL(url, origin), options);
async function waitFor(predicate) {
  const deadline = Date.now() + 15000;
  while (Date.now() < deadline) {
    if (predicate()) return;
    if (doc.querySelector('h1')?.textContent === 'Unable to load this view')
      throw new Error(doc.querySelector('#content').textContent);
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw new Error('UI deadline: '+doc.querySelector('#content').textContent.slice(0,300)+'; toast '+doc.querySelector('#toast').textContent);
}
async function go(hash) {
  window.location.hash = hash;
  // Happy DOM does not emit native hashchange on Location assignment.
  window.dispatchEvent(new window.HashChangeEvent("hashchange"));
  await waitFor(() => doc.querySelector('h1'));
}
window.document.write(
  await readFile(
    new URL("../aaron_model_testing/static/index.html", import.meta.url),
    "utf8",
  ),
);
window.eval(
  await readFile(
    new URL("../aaron_model_testing/static/app.js", import.meta.url),
    "utf8",
  ),
);
const doc = window.document;
try {
  await waitFor(() => doc.querySelector('h1'));
  assert.match(doc.querySelector("h1").textContent, /leaderboard/);
  assert.ok(doc.querySelector('[data-action="scan"]'));
  for (const [hash, title] of [
    ["models", "Model inventory"],
    ["runs", "Run history"],
    ["tests", "Benchmark definitions"],
    ["settings", "Runtime settings"],
  ]) {
    await go(hash);
    await waitFor(() => doc.querySelector('h1')?.textContent === title);
    assert.equal(doc.querySelector("h1").textContent, title);
  }
  assert.equal(
    doc.querySelector('input[name="server_binary"]').value,
    (await (await fetch(origin + "/api/settings")).json()).server_binary,
  );
  await go("models");
  await waitFor(() => doc.querySelector('h1')?.textContent === 'Model inventory');
  const profiles = await (await fetch(origin + '/api/profiles')).json();
  const modelLink = profiles.length
    ? doc.querySelector(`a[href="#model/${profiles[0].model_id}"]`)
    : doc.querySelector('a[href^="#model/"]');
  if (modelLink) {
    await go(modelLink.getAttribute("href"));
    await waitFor(() => doc.querySelector('[data-action="profile"]'));
    assert.ok(doc.querySelector('[data-action="profile"]'));
    doc.querySelector('[data-action="profile"]').click();
    await waitFor(() => doc.querySelector('#profile-form textarea[name="config"]'));
    assert.ok(
      doc
        .querySelector('#profile-form textarea[name="config"]')
        .value.includes("flash_attn"),
    );
    doc.querySelector("#close-modal").click();
    doc.querySelector('[data-action="run"]').click();
    await waitFor(() => doc.querySelector('#run-form'));
    assert.ok(doc.querySelector("#run-form"));
    if (profiles.length) assert.ok(doc.querySelector("#run-profile").options.length);
    doc.querySelector("#close-modal").click();
  }
  await go("runs");
  await waitFor(() => doc.querySelector('h1')?.textContent === 'Run history');
  const runLink = doc.querySelector('a[href^="#run/"]');
  if (runLink) {
    await go(runLink.getAttribute("href"));
    await waitFor(() => doc.querySelector('#content').textContent.includes('Reproduce this run'));
    assert.match(
      doc.querySelector("#content").textContent,
      /Reproduce this run/,
    );
    const recorded = await (await fetch(origin + '/api/runs/' + runLink.getAttribute('href').split('/')[1])).json();
    const capability = recorded.records.find(r => r.type === 'capability');
    const inspect = capability
      ? doc.querySelector(`[data-action="inspect"][data-id="${capability.id}"]`)
      : doc.querySelector('[data-action="inspect"]');
    if (inspect) {
      inspect.click();
      await waitFor(() => doc.querySelector('#modal-body pre'));
      assert.ok(doc.querySelector("#modal-body pre"));
      if (capability) assert.match(doc.querySelector('#modal-body').textContent, /Raw model answer/);
      doc.querySelector("#close-modal").click();
    }
  }
  const measured = (await (await fetch(origin + '/api/runs')).json())
    .filter(r => r.status === 'completed' && r.summary?.metrics?.generation_tps?.n)
    .slice(0, 2);
  await go('compare');
  await waitFor(() => doc.querySelector('h1')?.textContent === 'Compare profiles');
  if (measured.length === 2) {
    for (const run of measured) {
      const checkbox = doc.querySelector(`[data-select="${run.id}"]`);
      checkbox.checked = true;
      checkbox.dispatchEvent(new window.Event('change', { bubbles: true }));
    }
    doc.querySelector('[data-action="compare"]').click();
    await waitFor(() => doc.querySelector('h1')?.textContent === 'Profile comparison');
    assert.ok(doc.querySelector('svg'), 'Measured comparison renders SVG charts');
    assert.match(doc.querySelector('#content').textContent, /VRAM sampled peak/);
  }
  assert.deepEqual(errors, []);
  assert.doesNotMatch(
    doc.querySelector("#content").textContent,
    /Unable to load/,
  );
  console.log(
    "PASS: live UI navigation, inventory, profile editor, run form, tests, settings, history, response inspector and comparison charts",
  );
} finally {
  await window.happyDOM.abort();
  window.close();
}
