(function () {
  'use strict';

  var menu = document.getElementById('account-menu');
  if (!menu) return;

  // A <details> stays open until its own summary is clicked again, which is
  // not how a dropdown should behave.
  document.addEventListener('click', function (event) {
    if (menu.open && !menu.contains(event.target)) menu.open = false;
  });

  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && menu.open) {
      menu.open = false;
      var summary = menu.querySelector('summary');
      if (summary) summary.focus();
    }
  });
})();
