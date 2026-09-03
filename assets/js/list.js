(function () {
  "use strict";

  var input = document.getElementById("filter-input");
  var countEl = document.getElementById("word-count");
  var listRoot = document.getElementById("word-list");
  var letterJump = document.getElementById("letter-jump");
  var copyBtn = document.getElementById("copy-btn");
  var downloadBtn = document.getElementById("download-btn");
  if (!listRoot) return;

  var cards = Array.prototype.slice.call(listRoot.querySelectorAll("[data-word]"));
  var groups = Array.prototype.slice.call(listRoot.querySelectorAll(".letter-group"));
  var jumpLinks = letterJump ? Array.prototype.slice.call(letterJump.querySelectorAll("a")) : [];
  var total = cards.length;

  function visibleWords() {
    return cards.filter(function (c) { return !c.hidden; }).map(function (c) {
      return c.getAttribute("data-word");
    });
  }

  function applyFilter() {
    var q = (input.value || "").trim().toLowerCase();
    var visibleCount = 0;

    cards.forEach(function (c) {
      var match = !q || c.getAttribute("data-word").indexOf(q) !== -1;
      c.hidden = !match;
      if (match) visibleCount++;
    });

    groups.forEach(function (g) {
      var anyVisible = g.querySelector("[data-word]:not([hidden])");
      g.hidden = !anyVisible;
    });

    jumpLinks.forEach(function (a) {
      var targetId = a.getAttribute("href").slice(1);
      var group = document.getElementById(targetId);
      var disabled = !group || group.hidden;
      a.classList.toggle("dim", disabled);
      a.style.opacity = disabled ? "0.3" : "";
      a.style.pointerEvents = disabled ? "none" : "";
    });

    if (countEl) {
      countEl.textContent = "Showing " + visibleCount.toLocaleString() + " of " + total.toLocaleString() + " words";
    }
  }

  if (input) {
    input.addEventListener("input", applyFilter);
  }

  if (letterJump) {
    letterJump.addEventListener("click", function (e) {
      var a = e.target.closest("a");
      if (!a) return;
      var group = document.getElementById(a.getAttribute("href").slice(1));
      if (group && !group.hidden) {
        e.preventDefault();
        group.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    });
  }

  function flashLabel(btn, label, revertTo) {
    var original = revertTo || btn.textContent;
    btn.textContent = label;
    setTimeout(function () { btn.textContent = original; }, 1400);
  }

  if (copyBtn) {
    copyBtn.addEventListener("click", function () {
      var text = visibleWords().join("\n");
      var original = copyBtn.textContent;
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(function () {
          flashLabel(copyBtn, "Copied!", original);
        }, function () {
          flashLabel(copyBtn, "Copy failed", original);
        });
      } else {
        var ta = document.createElement("textarea");
        ta.value = text;
        ta.style.position = "fixed";
        ta.style.opacity = "0";
        document.body.appendChild(ta);
        ta.select();
        try { document.execCommand("copy"); flashLabel(copyBtn, "Copied!", original); }
        catch (e) { flashLabel(copyBtn, "Copy failed", original); }
        document.body.removeChild(ta);
      }
    });
  }

  if (downloadBtn) {
    downloadBtn.addEventListener("click", function () {
      var text = visibleWords().join("\n") + "\n";
      var blob = new Blob([text], { type: "text/plain" });
      var url = URL.createObjectURL(blob);
      var a = document.createElement("a");
      a.href = url;
      a.download = (document.title.split("|")[0].trim().toLowerCase().replace(/[^a-z0-9]+/g, "-") || "words") + ".txt";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    });
  }
})();
