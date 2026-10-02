// ==UserScript==
// @name         Radar — remplissage des candidatures
// @namespace    intern-radar
// @version      __VERSION__
// @description  Remplit les formulaires Greenhouse, Lever et Ashby avec le kit de candidature d'intern-radar. N'envoie jamais rien : c'est toi qui cliques sur « Submit ».
// @match        https://job-boards.greenhouse.io/*
// @match        https://job-boards.eu.greenhouse.io/*
// @match        https://boards.greenhouse.io/*
// @match        https://boards.eu.greenhouse.io/*
// @match        https://jobs.lever.co/*
// @match        https://jobs.eu.lever.co/*
// @match        https://jobs.ashbyhq.com/*
// @grant        GM.xmlHttpRequest
// @grant        GM_xmlhttpRequest
// @connect      __HOST__
// @run-at       document-idle
// ==/UserScript==

(function () {
  "use strict";

  const BASE = "__BASE__";
  const STORE_KEY = "radar-kit";

  // --- data -----------------------------------------------------------------

  function request(url, binary) {
    const gm = (typeof GM !== "undefined" && GM.xmlHttpRequest) ||
      (typeof GM_xmlhttpRequest !== "undefined" && GM_xmlhttpRequest);
    if (!gm) return Promise.reject(new Error("API du gestionnaire de scripts absente"));
    return new Promise((resolve, reject) => {
      gm({
        method: "GET",
        url,
        responseType: binary ? "arraybuffer" : "text",
        timeout: 15000,
        onload: (r) => (r.status === 200 ? resolve(r.response) : reject(new Error("HTTP " + r.status))),
        onerror: () => reject(new Error("web app injoignable (Tailscale ?)")),
        ontimeout: () => reject(new Error("délai dépassé")),
      });
    });
  }

  function fromFragment() {
    // "#radar=<ref>" or "#radar=<ref>.<base64url JSON>" (offline copy of the kit)
    const match = location.hash.match(/radar=(\d+)(?:\.([A-Za-z0-9_-]+))?/);
    if (!match) return null;
    let kit = null;
    if (match[2]) {
      try {
        const b64 = match[2].replace(/-/g, "+").replace(/_/g, "/");
        const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
        kit = JSON.parse(new TextDecoder().decode(bytes));
      } catch (e) {
        kit = null;
      }
    }
    return { ref: Number(match[1]), kit };
  }

  async function loadKit() {
    const lang = (document.documentElement.lang || "").startsWith("fr") ? "fr" : "en";
    let found = fromFragment();
    if (found) {
      sessionStorage.setItem(STORE_KEY, JSON.stringify(found));
    } else {
      try {
        found = JSON.parse(sessionStorage.getItem(STORE_KEY) || "null");
      } catch (e) {
        found = null;
      }
    }
    let ref = found && found.ref;
    try {
      if (!ref) {
        const lookup = JSON.parse(
          await request(BASE + "/api/kit/lookup?url=" + encodeURIComponent(location.href))
        );
        ref = lookup.ref;
      }
      return { kit: JSON.parse(await request(BASE + "/api/kit/" + ref + ".json?lang=" + lang)), online: true };
    } catch (error) {
      if (found && found.kit) return { kit: found.kit, online: false, error };
      throw error;
    }
  }

  // --- form helpers -----------------------------------------------------------

  function labelOf(el) {
    const aria = el.getAttribute("aria-label");
    if (aria) return aria;
    if (el.id) {
      const label = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
      if (label) return label.innerText;
    }
    const by = el.getAttribute("aria-labelledby");
    if (by) {
      const label = document.getElementById(by.split(" ")[0]);
      if (label) return label.innerText;
    }
    const box = el.closest("label, fieldset, li, .field, [class*='field'], [class*='question']");
    if (box) {
      const title = box.querySelector("label, legend, .text, [class*='label'], [class*='title']");
      return (title || box).innerText.slice(0, 200);
    }
    return el.name || el.placeholder || "";
  }

  function isEmpty(el) {
    return !el.value || !el.value.trim();
  }

  function isChoiceWidget(el) {
    return el.getAttribute("role") === "combobox" || el.hasAttribute("aria-autocomplete") ||
      el.getAttribute("aria-haspopup") === "listbox" || el.readOnly;
  }

  function setValue(el, value) {
    // Native setter + events, so that React-controlled inputs keep the value.
    const proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, "value").set;
    el.focus();
    setter.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    el.blur();
  }

  function isRequired(el) {
    return el.required || el.getAttribute("aria-required") === "true" || /\*/.test(labelOf(el));
  }

  function visible(el) {
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  }

  // --- what goes where ----------------------------------------------------------

  function rules(kit) {
    const f = kit.fields;
    const authorised = kit.work_authorisation === "free" || kit.work_authorisation === "self_arranged";
    const sponsor = !authorised;
    return [
      [/preferred (first )?name/i, ""],
      [/first\s*name|pr[ée]nom|given name/i, f.first_name],
      [/last\s*name|surname|family name|nom de famille/i, f.last_name],
      [/^\s*(full\s*)?name\s*[*✱]?\s*$|your name/i, f.full_name],
      [/e-?mail/i, f.email],
      [/phone|mobile|t[ée]l[ée]phone/i, f.phone],
      [/linkedin/i, f.linkedin],
      [/github|website|portfolio|personal site|site web/i, f.github],
      [/current (location|city)|^location|city|ville|where are you (located|based)/i, f.location],
      [/school|university|college|[ée]cole|institution/i, f.school],
      [/discipline|field of study|major|sp[ée]cialit/i, f.discipline],
      [/degree|dipl[ôo]me/i, f.degree],
      [/graduat/i, f.graduation_month && f.graduation_year
        ? String(f.graduation_month).padStart(2, "0") + "/" + f.graduation_year : ""],
      [/how did you (hear|find)|comment avez-vous connu/i, f.heard_from],
      [/languages? spoken|langues/i, f.languages],
      [/(legally )?authori[sz]ed to work|autoris[ée] à travailler/i, authorised ? "Yes" : "No"],
      [/sponsor/i, sponsor ? "Yes" : "No"],
    ];
  }

  function byAttribute(kit, el) {
    // Fields the ATS names the same way on every form.
    const f = kit.fields;
    const known = {
      first_name: f.first_name, last_name: f.last_name, email: f.email, phone: f.phone,
      name: f.full_name, _systemfield_name: f.full_name, _systemfield_email: f.email,
      _systemfield_phone: f.phone, "urls[LinkedIn]": f.linkedin, "urls[GitHub]": f.github,
      "urls[Portfolio]": f.github, "urls[Other]": "",
    };
    for (const key of [el.name, el.id]) {
      if (key && Object.prototype.hasOwnProperty.call(known, key)) return known[key];
    }
    return undefined;
  }

  function fillText(kit, report) {
    const inputs = document.querySelectorAll(
      "input[type=text], input[type=email], input[type=tel], input[type=url], input:not([type]), textarea"
    );
    for (const el of inputs) {
      if (!visible(el) || !isEmpty(el)) continue;
      if (isChoiceWidget(el)) continue;
      const label = labelOf(el);
      const known = byAttribute(kit, el);
      if (known !== undefined) {
        if (known) {
          setValue(el, known);
          report.filled.push((label || el.name).trim().slice(0, 40));
        }
        continue;
      }
      for (const [pattern, value] of rules(kit)) {
        if (pattern.test(label)) {
          if (value) {
            setValue(el, value);
            report.filled.push(label.trim().slice(0, 40));
          }
          break;
        }
      }
    }
  }

  function fillYesNo(kit, report) {
    // Radio groups answering the work authorisation and sponsorship questions.
    const authorised = kit.work_authorisation === "free" || kit.work_authorisation === "self_arranged";
    const groups = new Map();
    for (const radio of document.querySelectorAll("input[type=radio]")) {
      if (!groups.has(radio.name)) groups.set(radio.name, []);
      groups.get(radio.name).push(radio);
    }
    for (const radios of groups.values()) {
      if (radios.some((r) => r.checked)) continue;
      const box = radios[0].closest("fieldset, li, [class*='question'], [class*='field']");
      const question = box ? box.innerText : "";
      let want = null;
      if (/sponsor/i.test(question)) want = authorised ? "no" : "yes";
      else if (/authori[sz]ed to work|autoris/i.test(question)) want = authorised ? "yes" : "no";
      if (!want) continue;
      const choice = radios.find((r) => new RegExp("^\\s*" + want + "\\b", "i").test(labelOf(r) || r.value));
      if (choice) {
        choice.click();
        report.filled.push(question.split("\n")[0].slice(0, 40));
      }
    }
  }

  async function attach(kit, report) {
    const slots = {
      cv: /resume|cv|curriculum/i,
      letter: /cover/i,
    };
    for (const input of document.querySelectorAll("input[type=file]")) {
      if (input.files && input.files.length) continue;
      const label = labelOf(input) + " " + (input.name || "") + " " + (input.id || "");
      const kind = slots.letter.test(label) ? "letter" : slots.cv.test(label) ? "cv" : null;
      const url = kind && kit.documents && kit.documents[kind];
      if (!url) continue;
      try {
        const data = await request(url, true);
        const name = (kind === "cv" ? "CV" : "Cover_Letter") + ".pdf";
        const transfer = new DataTransfer();
        transfer.items.add(new File([data], name, { type: "application/pdf" }));
        input.files = transfer.files;
        input.dispatchEvent(new Event("input", { bubbles: true }));
        input.dispatchEvent(new Event("change", { bubbles: true }));
        report.filled.push(kind === "cv" ? "CV joint" : "Lettre jointe");
      } catch (error) {
        report.missing.push((kind === "cv" ? "CV" : "Lettre") + " à joindre à la main (" + error.message + ")");
      }
    }
  }

  function outlineMissing(report) {
    for (const el of document.querySelectorAll("input, textarea, select")) {
      if (!visible(el) || ["hidden", "submit", "button", "radio", "checkbox"].includes(el.type)) continue;
      const empty = el.type === "file" ? !(el.files && el.files.length) : isEmpty(el);
      if (empty && isRequired(el)) {
        el.style.outline = "3px solid #f59e0b";
        el.style.outlineOffset = "2px";
        report.missing.push(labelOf(el).replace(/\s+/g, " ").trim().slice(0, 60));
      }
    }
  }

  async function fill(kit) {
    const report = { filled: [], missing: [] };
    fillText(kit, report);
    fillYesNo(kit, report);
    await attach(kit, report);
    outlineMissing(report);
    return report;
  }

  // --- panel ------------------------------------------------------------------

  function panel(kit, online, warning) {
    const host = document.createElement("div");
    host.style.cssText = "position:fixed;right:12px;bottom:12px;z-index:2147483647";
    const root = host.attachShadow({ mode: "open" });
    const escape = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
    const rows = kit.answers.map((a, i) =>
      '<div class="row"><div class="q">' + escape(a.question) + '</div><div class="a" id="a' + i + '">' +
      escape(a.answer) + '</div><button data-i="' + i + '">Copier</button></div>'
    ).join("");
    root.innerHTML =
      "<style>" +
      ":host{all:initial}*{box-sizing:border-box;font:14px -apple-system,system-ui,sans-serif}" +
      ".fab{background:#2f6fde;color:#fff;border:0;border-radius:24px;padding:10px 16px;font-weight:600;box-shadow:0 4px 14px #0004}" +
      ".box{display:none;width:min(92vw,380px);max-height:70vh;overflow:auto;background:#fff;color:#1d1d1f;border-radius:14px;padding:12px;box-shadow:0 8px 30px #0005;margin-bottom:8px}" +
      ".open .box{display:block}h3{margin:0 0 4px;font-size:15px}.muted{color:#6b6b70;font-size:12px}" +
      ".go{width:100%;background:#2f6fde;color:#fff;border:0;border-radius:10px;padding:10px;font-weight:600;margin:8px 0}" +
      ".row{border-top:1px solid #e3e3e0;padding:6px 0}.q{color:#6b6b70;font-size:12px}.a{white-space:pre-wrap;margin:2px 0}" +
      ".row button{background:#eef2fb;border:0;border-radius:8px;padding:3px 9px;font-size:12px}" +
      ".warn{color:#c2410c}.ok{color:#15803d}ul{margin:4px 0;padding-left:18px}" +
      "</style>" +
      '<div class="wrap"><div class="box">' +
      "<h3>" + escape(kit.offer.company) + "</h3><div class='muted'>" + escape(kit.offer.title) + "</div>" +
      (warning ? "<p class='warn'>" + escape(warning) + "</p>" : "") +
      '<button class="go">Remplir le formulaire</button><div class="result"></div>' +
      "<p class='muted'>Le script ne clique jamais sur « Submit » : relis, complète les champs en orange, puis envoie toi-même.</p>" +
      (kit.why ? '<div class="row"><div class="q">Pourquoi cette entreprise</div><div class="a" id="why">' +
        escape(kit.why) + '</div><button data-why="1">Copier</button></div>' : "") +
      rows +
      (online ? '<p class="muted"><a href="' + escape(kit.offer.page) + '" target="_blank">Ouvrir le kit dans la web app</a></p>' : "") +
      '</div><button class="fab">📡 Radar</button></div>';
    const wrap = root.querySelector(".wrap");
    root.querySelector(".fab").addEventListener("click", () => wrap.classList.toggle("open"));
    root.querySelector(".box").addEventListener("click", async (event) => {
      const button = event.target.closest("button");
      if (!button) return;
      if (button.classList.contains("go")) {
        button.disabled = true;
        button.textContent = "Remplissage…";
        const report = await fill(kit);
        button.disabled = false;
        button.textContent = "Remplir à nouveau";
        root.querySelector(".result").innerHTML =
          "<p class='ok'>" + report.filled.length + " champ(s) rempli(s).</p>" +
          (report.missing.length
            ? "<p class='warn'>À compléter (" + report.missing.length + ") :</p><ul>" +
              report.missing.map((m) => "<li>" + escape(m) + "</li>").join("") + "</ul>"
            : "<p class='ok'>Aucun champ obligatoire vide détecté.</p>");
        return;
      }
      const source = button.dataset.why ? root.getElementById("why") : root.getElementById("a" + button.dataset.i);
      if (!source) return;
      try {
        await navigator.clipboard.writeText(source.textContent);
        button.textContent = "✓ Copié";
        setTimeout(() => (button.textContent = "Copier"), 1500);
      } catch (e) {
        button.textContent = "Copie refusée";
      }
    });
    document.body.appendChild(host);
  }

  function waitForForm(timeout) {
    return new Promise((resolve) => {
      const ready = () => document.querySelector("input[type=email], input[name*=email], input[type=file]");
      if (ready()) return resolve(true);
      const observer = new MutationObserver(() => {
        if (ready()) {
          observer.disconnect();
          resolve(true);
        }
      });
      observer.observe(document.documentElement, { childList: true, subtree: true });
      setTimeout(() => {
        observer.disconnect();
        resolve(Boolean(ready()));
      }, timeout);
    });
  }

  async function main() {
    if (!(await waitForForm(20000))) return; // not an application form
    let loaded;
    try {
      loaded = await loadKit();
    } catch (error) {
      return; // offer unknown to the radar: stay silent
    }
    const warning = loaded.online ? "" :
      "Web app injoignable (" + loaded.error.message + ") : réponses copiées depuis le lien, PDF à joindre à la main.";
    panel(loaded.kit, loaded.online, warning);
  }

  window.__radar = { fill, rules, setValue, labelOf, fromFragment };
  main();
})();
