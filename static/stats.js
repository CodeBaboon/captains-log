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
