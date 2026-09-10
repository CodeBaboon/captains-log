(function () {
  'use strict';

  var form = document.getElementById('filters');
  if (!form) return;

  var panel = form.querySelector('.picker');
  if (!panel) return;

  var boxes = panel.querySelectorAll('input[type="checkbox"]');

  // All and None are shortcuts, not filter states. Selecting nothing means the
  // same thing as selecting everything, so both land on an unfiltered view.
  panel.addEventListener('click', function (event) {
    var action = event.target.getAttribute('data-pick');
    if (!action) return;
    event.preventDefault();
    Array.prototype.forEach.call(boxes, function (box) {
      box.checked = action === 'all';
    });
    syncActions();
  });

  function syncActions() {
    var anyChecked = Array.prototype.some.call(boxes, function (b) {
      return b.checked;
    });
    var all = panel.querySelector('[data-pick="all"]');
    var none = panel.querySelector('[data-pick="none"]');
    if (all) all.classList.toggle('chip-on', !anyChecked);
    if (none) none.classList.toggle('chip-on', false);
  }

  panel.addEventListener('change', function (event) {
    if (event.target.type === 'checkbox') syncActions();
  });

  syncActions();
})();

(function () {
  'use strict';

  var table = document.getElementById('record-table');
  if (!table) return;

  var body = table.tBodies[0];
  var buttons = table.querySelectorAll('.led-sort');

  // The table arrives already sorted by wins descending, so sorting is a
  // progressive enhancement: without JS the default order still makes sense.
  var current = 'wins';
  var ascending = false;

  function valueOf(row, key, type) {
    var raw = row.getAttribute('data-' + key);
    if (type === 'number') {
      // Blank means the captain has no scored games; those sort last either way.
      return raw === '' ? null : parseFloat(raw);
    }
    return (raw || '').toLowerCase();
  }

  function sortBy(key, type) {
    var rows = Array.prototype.slice.call(body.rows);

    rows.sort(function (a, b) {
      var x = valueOf(a, key, type);
      var y = valueOf(b, key, type);

      if (x === null && y === null) return 0;
      if (x === null) return 1;
      if (y === null) return -1;

      var order = x < y ? -1 : (x > y ? 1 : 0);
      if (order === 0) {
        // Ties fall back to captain name so the order never wobbles.
        var an = valueOf(a, 'captain', 'text');
        var bn = valueOf(b, 'captain', 'text');
        return an < bn ? -1 : (an > bn ? 1 : 0);
      }
      return ascending ? order : -order;
    });

    rows.forEach(function (row) { body.appendChild(row); });
  }

  function paint(active) {
    Array.prototype.forEach.call(buttons, function (button) {
      var isActive = button === active;
      button.classList.toggle('is-sorted', isActive);
      button.classList.toggle('is-ascending', isActive && ascending);
      button.closest('th').setAttribute(
        'aria-sort',
        isActive ? (ascending ? 'ascending' : 'descending') : 'none'
      );
    });
  }

  Array.prototype.forEach.call(buttons, function (button) {
    button.addEventListener('click', function () {
      var key = button.dataset.key;
      var type = button.dataset.type;

      if (key === current) {
        ascending = !ascending;
      } else {
        current = key;
        // Names read best A to Z; numbers read best highest first.
        ascending = type === 'text';
      }

      sortBy(key, type);
      paint(button);
    });
  });
})();
