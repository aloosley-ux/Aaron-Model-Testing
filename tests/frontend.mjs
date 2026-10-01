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
    if (doc.querySelector("h1")?.textContent === "Unable to load this view")
      throw new Error(doc.querySelector("#content").textContent);
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(
    "UI deadline: " +
      doc.querySelector("#content").textContent.slice(0, 300) +
      "; toast " +
      doc.querySelector("#toast").textContent,
  );
}
async function go(hash) {
  window.location.hash = hash;
  // Happy DOM does not emit native hashchange on Location assignment.
  window.dispatchEvent(new window.HashChangeEvent("hashchange"));
  await waitFor(() => doc.querySelector("h1"));
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
  await waitFor(() => doc.querySelector("h1"));
  assert.match(doc.querySelector("h1").textContent, /leaderboard/);
  assert.ok(doc.querySelector('[data-action="scan"]'));
  for (const [hash, title] of [
    ["models", "Model inventory"],
    ["runs", "Run history"],
    ["tests", "Benchmark definitions"],
    ["settings", "Runtime settings"],
  ]) {
    await go(hash);
    await waitFor(() => doc.querySelector("h1")?.textContent === title);
    assert.equal(doc.querySelector("h1").textContent, title);
  }
  assert.equal(
    doc.querySelector('input[name="server_binary"]').value,
    (await (await fetch(origin + "/api/settings")).json()).server_binary,
  );
  await go("models");
  await waitFor(
    () => doc.querySelector("h1")?.textContent === "Model inventory",
  );
  const profiles = await (await fetch(origin + "/api/profiles")).json();
  const modelLink = profiles.length
    ? doc.querySelector(`a[href="#model/${profiles[0].model_id}"]`)
    : doc.querySelector('a[href^="#model/"]');
  if (modelLink) {
    await go(modelLink.getAttribute("href"));
    await waitFor(() => doc.querySelector('[data-action="profile"]'));
    assert.ok(doc.querySelector('[data-action="profile"]'));
    doc.querySelector('[data-action="profile"]').click();
    await waitFor(() =>
      doc.querySelector('#profile-form textarea[name="config"]'),
    );
    assert.ok(
      doc
        .querySelector('#profile-form textarea[name="config"]')
        .value.includes("flash_attn"),
    );
    doc.querySelector("#close-modal").click();
    doc.querySelector('[data-action="run"]').click();
    await waitFor(() => doc.querySelector("#run-form"));
    assert.ok(doc.querySelector("#run-form"));
    if (profiles.length)
      assert.ok(doc.querySelector("#run-profile").options.length);
    const form = doc.querySelector("#run-form");
    assert.equal(form.elements.qualification.value, "quick");
    assert.equal(form.elements.contexts.value, "2048,8192");
    assert.equal(form.elements.long_context.checked, false);
    for (const [kind, contexts, long, smoke] of [
      ["full", "2048,4096,8192", true, false],
      ["smoke", "2048,4096,8192", false, true],
      ["quick", "2048,8192", false, false],
    ]) {
      form.elements.qualification.value = kind;
      form.elements.qualification.dispatchEvent(
        new window.Event("change", { bubbles: true }),
      );
      assert.equal(form.elements.contexts.value, contexts);
      assert.equal(form.elements.long_context.checked, long);
      assert.equal(form.elements.smoke.checked, smoke);
      assert.equal(form.elements.stage.disabled, true);
    }
    if (profiles.length) {
      const realFetch = window.fetch;
      let submitted;
      window.fetch = (url, options) => {
        if (url === "/api/runs" && options?.method === "POST") {
          submitted = JSON.parse(options.body);
          return Promise.resolve(
            new Response(JSON.stringify({ id: "dom-only-queued" }), {
              status: 202,
            }),
          );
        }
        return realFetch(url, options);
      };
      try {
        form.dispatchEvent(
          new window.Event("submit", { bubbles: true, cancelable: true }),
        );
        await waitFor(() => submitted);
        assert.equal(submitted.qualification, "quick");
        assert.equal(submitted.stage, "full");
        assert.deepEqual(submitted.contexts, [2048, 8192]);
        assert.equal(submitted.repeats, 3);
        assert.equal(submitted.long_context, false);
        assert.equal(submitted.load_repeats, 3);
        await waitFor(() => !doc.querySelector("#modal").open);
      } finally {
        window.fetch = realFetch;
      }
    }
    doc.querySelector("#close-modal").click();
  }
  await go("runs");
  await waitFor(() => doc.querySelector("h1")?.textContent === "Run history");
  const runLink = doc.querySelector('a[href^="#run/"]');
  if (runLink) {
    await go(runLink.getAttribute("href"));
    await waitFor(() =>
      doc.querySelector("#content").textContent.includes("Reproduce this run"),
    );
    assert.match(
      doc.querySelector("#content").textContent,
      /Reproduce this run/,
    );
    const recorded = await (
      await fetch(
        origin + "/api/runs/" + runLink.getAttribute("href").split("/")[1],
      )
    ).json();
    const capability = recorded.records.find((r) => r.type === "capability");
    const inspect = capability
      ? doc.querySelector(`[data-action="inspect"][data-id="${capability.id}"]`)
      : doc.querySelector('[data-action="inspect"]');
    if (inspect) {
      inspect.click();
      await waitFor(() => doc.querySelector("#modal-body pre"));
      assert.ok(doc.querySelector("#modal-body pre"));
      if (capability)
        assert.match(
          doc.querySelector("#modal-body").textContent,
          /Raw model answer/,
        );
      doc.querySelector("#close-modal").click();
    }
  }
  const measured = (await (await fetch(origin + "/api/runs")).json())
    .filter(
      (r) => r.status === "completed" && r.summary?.metrics?.generation_tps?.n,
    )
    .slice(0, 2);
  await go("compare");
  await waitFor(
    () => doc.querySelector("h1")?.textContent === "Compare profiles",
  );
  if (measured.length === 2) {
    for (const run of measured) {
      const checkbox = doc.querySelector(`[data-select="${run.id}"]`);
      checkbox.checked = true;
      checkbox.dispatchEvent(new window.Event("change", { bubbles: true }));
    }
    doc.querySelector('[data-action="compare"]').click();
    await waitFor(
      () => doc.querySelector("h1")?.textContent === "Profile comparison",
    );
    assert.ok(
      doc.querySelector("svg"),
      "Measured comparison renders SVG charts",
    );
    assert.match(
      doc.querySelector("#content").textContent,
      /VRAM sampled peak/,
    );
  }
  // Deterministic polling coverage, with no model execution or user-data writes.
  const realFetch = window.fetch;
  const fixture = {
    id: "live-fixture",
    status: "running",
    stage: "full",
    model: { name: "Live <model>" },
    profile: { name: "FAST" },
    request: { qualification: "quick" },
    benchmark: { id: "agent-core-v1.1" },
    created_at: new Date().toISOString(),
    summary: {},
    records: [],
    live: {
      status: "running",
      completed_samples: 0,
      planned_samples: 3,
      phase: "Loading",
      elapsed_seconds: 1,
      capability: null,
      capability_status: "pending",
      resources: {},
    },
  };
  window.fetch = (url, options) => {
    if (url === "/api/runs/live-fixture")
      return Promise.resolve(new Response(JSON.stringify(fixture)));
    if (url === "/api/runs/live-fixture/live")
      return Promise.resolve(
        new Response(
          JSON.stringify({
            id: fixture.id,
            model: fixture.model.name,
            profile: "FAST",
            stage: "full",
            qualification: "quick",
            job_id: "dom-only-job",
            summary: fixture.summary,
            live: fixture.live,
          }),
        ),
      );
    return realFetch(url, options);
  };
  try {
    await go("run/live-fixture");
    await waitFor(
      () => doc.querySelector("#live-monitor h2")?.textContent === "LIVE RUN",
    );
    assert.match(
      doc.querySelector("#run-cards").textContent,
      /LIVE \/ PARTIAL CAPABILITYPending/,
    );
    assert.doesNotMatch(
      doc.querySelectorAll("#run-cards .card")[2].textContent,
      /0%/,
    );
    fixture.live = {
      ...fixture.live,
      completed_samples: 2,
      progress_fraction: 2 / 3,
      phase: "Capability",
      current_test: "<img src=x onerror=alert(1)>",
      current_context: 2048,
      current_repeat: 3,
      elapsed_seconds: 20,
      eta_seconds: 10,
      pass_count: 1,
      fail_count: 1,
      error_count: 0,
      capability: 0.5,
      capability_samples: 2,
      capability_status: "valid",
      reliability: 1,
      generation_tps: 55,
      prompt_tps: 2600,
      events: Array.from({ length: 40 }, (_, i) => ({
        outcome: "PASS",
        test: `sample_${i}`,
        context: 2048,
        repeat: 1,
      })),
    };
    await waitFor(() =>
      doc.querySelector("#live-monitor").textContent.includes("2 / 3 samples"),
    );
    assert.equal(doc.querySelectorAll(".activity-feed li").length, 30);
    assert.equal(doc.querySelector("#live-monitor img"), null);
    assert.match(doc.querySelector("#run-cards").textContent, /50%/);
    assert.match(doc.querySelector("#run-cards").textContent, /55/);
    fixture.status = "completed";
    fixture.live.status = "completed";
    fixture.summary = {
      capability: 0.5,
      capability_samples: 3,
      reliability: 1,
      errors: 0,
    };
    await waitFor(() =>
      doc.querySelector("#run-cards").textContent.includes("FINAL CAPABILITY"),
    );
    assert.doesNotMatch(doc.querySelector("#run-cards").textContent, /LIVE/);
    fixture.summary = {
      capability: null,
      capability_status: "invalid",
      capability_samples: 3,
      capability_warning: "Parser cannot safely identify the final answer",
      reliability: 1,
    };
    await go("run/live-fixture");
    await waitFor(() =>
      doc.querySelector("#run-cards").textContent.includes("Unavailable"),
    );
    assert.match(
      doc.querySelector("#content").textContent,
      /Parser cannot safely/,
    );
    assert.doesNotMatch(
      doc.querySelectorAll("#run-cards .card")[2].textContent,
      /0%/,
    );
  } finally {
    window.fetch = realFetch;
  }
  // Optional real native run observation, started externally on owned port 1235.
  if (process.env.AMT_TEST_LIVE_RUN) {
    await go("run/" + process.env.AMT_TEST_LIVE_RUN);
    await waitFor(
      () => doc.querySelector("#live-monitor h2")?.textContent === "LIVE RUN",
    );
    const before = doc.querySelector(".run-progress").value;
    await waitFor(() => doc.querySelector(".run-progress")?.value > before);
    assert.match(
      doc.querySelector("#run-cards").textContent,
      /LIVE \/ PARTIAL/,
    );
    console.log("PASS: real native run progress increased in the polling DOM");
  }
  assert.deepEqual(errors, []);
  assert.doesNotMatch(
    doc.querySelector("#content").textContent,
    /Unable to load/,
  );
  console.log(
    "PASS: UI navigation, presets and submission, inspector, comparison, live polling, bounded activity, escaping and final/invalid states",
  );
} finally {
  await window.happyDOM.abort();
  window.close();
}
