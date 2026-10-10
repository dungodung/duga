// Progressive enhancement only: every page must keep working with this file
// absent (see SPEC.md section 12). Nothing here adds behaviour that isn't
// already available without it -- each block replaces a working
// form-submit round trip with the same result, locally.
//
// ES5 on purpose, and no dependencies: SPEC.md section 5 names low-end
// Android phones as the target, so no const/let, no arrow functions, no
// template literals, and no two-argument classList.toggle.
document.addEventListener("DOMContentLoaded", function () {
  // Auto-submit the interface language <select> on change, so JS users
  // don't need the extra button tap.
  var langSelect = document.getElementById("uselang");
  if (langSelect) {
    langSelect.addEventListener("change", function () {
      langSelect.form.submit();
    });
  }

  // Narrow the gap list's filters as soon as one changes, rather than after
  // the round trip: types to the chosen project, maturities to the chosen
  // project and type. Without this the server does the same narrowing on
  // submit (main.gaps), and drops a choice the earlier filters rule out.
  var projectSelect = document.getElementById("filter-project");
  var typeSelect = document.getElementById("filter-type");
  var maturitySelect = document.getElementById("filter-maturity");
  if (projectSelect && typeSelect && maturitySelect &&
      typeSelect.getAttribute("data-choices") &&
      maturitySelect.getAttribute("data-choices")) {
    var typeChoices = JSON.parse(typeSelect.getAttribute("data-choices"));
    var maturityChoices = JSON.parse(maturitySelect.getAttribute("data-choices"));

    // Each choice lists the [project, type] pairs it is possible for; an
    // empty filter value matches any.
    var possible = function (choice, project, type) {
      for (var i = 0; i < choice.combos.length; i++) {
        var combo = choice.combos[i];
        if ((!project || combo[0] === project) && (!type || combo[1] === type)) {
          return true;
        }
      }
      return false;
    };

    // Rebuilds everything after the "any" option, which the server
    // rendered already translated, and keeps the current choice if it is
    // still possible -- otherwise falls back to "any".
    var rebuild = function (select, choices, project, type) {
      var current = select.value;
      while (select.options.length > 1) {
        select.remove(1);
      }
      for (var i = 0; i < choices.length; i++) {
        if (!possible(choices[i], project, type)) continue;
        var option = document.createElement("option");
        option.value = choices[i].value;
        option.textContent = choices[i].label;
        select.appendChild(option);
      }
      select.value = current;
      if (select.value !== current) select.options[0].selected = true;
    };

    var rebuildMaturity = function () {
      rebuild(maturitySelect, maturityChoices, projectSelect.value, typeSelect.value);
    };
    projectSelect.addEventListener("change", function () {
      rebuild(typeSelect, typeChoices, projectSelect.value, "");
      rebuildMaturity();
    });
    typeSelect.addEventListener("change", rebuildMaturity);
  }

  // Filter the language picker as you type. Without this the same search
  // box still works -- it just round-trips to the server (main.home reads
  // ?q= and filters on the same data-search haystack), which is why the
  // markup is a real GET form.
  var search = document.getElementById("lang-q");
  var list = document.getElementById("lang-list");
  var empty = document.getElementById("lang-empty");
  var picker = document.getElementById("lang-picker");
  if (search && list) {
    // Snapshot once: these lists are server-rendered and never re-rendered.
    // Selecting .lang-item rather than children so a stray element inside
    // the <ul> can't be mistaken for a language. Items inside a closed
    // <details> are still in the DOM, so collapsing changes nothing here.
    var items = Array.prototype.slice.call(list.querySelectorAll(".lang-item"));
    // The suggested shortcut is a separate <ul> outside the disclosure, but
    // it is part of the same picker, so the same filter has to reach it.
    var suggested = document.querySelector(".lang-list-suggested");
    if (suggested) {
      items = items.concat(
        Array.prototype.slice.call(suggested.querySelectorAll(".lang-item"))
      );
    }
    if (items.length) {
      search.form.classList.add("js-live-search");
      // Whether the panel was opened by us rather than by the visitor, so
      // that clearing the box restores their choice instead of ours.
      var openedByUs = false;
      search.addEventListener("input", function () {
        // data-search is lowercased server-side by Python's str.lower(),
        // which folds non-ASCII more correctly than toLowerCase() does.
        // The two disagree for a few scripts (Turkish dotted I); that is
        // pre-existing and not worth a polyfill.
        var needle = search.value.trim().toLowerCase();
        var shown = 0;
        for (var i = 0; i < items.length; i++) {
          var match =
            !needle || items[i].getAttribute("data-search").indexOf(needle) !== -1;
          items[i].hidden = !match;
          if (match) shown++;
        }
        if (empty) empty.hidden = shown !== 0;
        // A match inside a closed <details> is a match nobody can see. The
        // template does the same thing server-side for ?q=.
        if (picker) {
          if (needle && !picker.open) {
            picker.open = true;
            openedByUs = true;
          } else if (!needle && openedByUs) {
            picker.open = false;
            openedByUs = false;
          }
        }
      });
    }
  }
});
