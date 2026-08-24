(function () {
  'use strict';

  var PLAYER_KEYS = ['glory', 'locations', 'endgame', 'card_vp',
                     'research', 'influence', 'military', 'mission'];
  var BOT_KEYS = ['glory', 'locations', 'endgame', 'card_vp',
                  'research', 'influence', 'military'];

  var form = document.getElementById('game-form');
  if (!form) return;

  var scoreBlock = document.getElementById('score-block');
  var burnNote = document.getElementById('burn-note');
  var missionRow = document.querySelector('.row-mission');
  var missionInput = document.getElementById('p_mission');
  var pTotal = document.getElementById('p-total');
  var bTotal = document.getElementById('b-total');

  function num(id) {
    var el = document.getElementById(id);
    if (!el || el.disabled) return 0;
    var raw = (el.value || '').trim();
    if (raw === '' || raw === '-') return 0;
    var parsed = parseInt(raw, 10);
    return isNaN(parsed) ? 0 : parsed;
  }

  function selected(name) {
    var el = form.querySelector('input[name="' + name + '"]:checked');
    return el ? el.value : null;
  }

  function recalculate() {
    var player = 0;
    var bot = 0;
    PLAYER_KEYS.forEach(function (key) { player += num('p_' + key); });
    BOT_KEYS.forEach(function (key) { bot += num('b_' + key); });

    pTotal.textContent = player;
    bTotal.textContent = bot;

    // There are no draws against the bot, so equal totals are still a loss.
    pTotal.classList.toggle('is-winning', player > bot);
    bTotal.classList.toggle('is-winning', bot >= player);
  }

  function applyBoardSide() {
    // Mission points only exist on the Advanced side of the captain board.
    var basic = selected('board_side') === 'basic';
    if (!missionRow || !missionInput) return;
    missionRow.classList.toggle('is-disabled', basic);
    missionInput.disabled = basic;
    if (basic) missionInput.value = '';
    recalculate();
  }

  function applyEnding() {
    var burned = selected('ending') === 'burn';
    scoreBlock.hidden = burned;
    burnNote.hidden = !burned;
  }

  form.addEventListener('input', function (event) {
    if (event.target.classList && event.target.classList.contains('cell')) {
      recalculate();
    }
  });

  form.addEventListener('change', function (event) {
    if (event.target.name === 'board_side') applyBoardSide();
    if (event.target.name === 'ending') applyEnding();
    if (event.target.name === 'played_on') updateStardate();
    if (event.target.classList.contains('captain-select')) toggleAddField(event.target);
  });

  // Decorative stardate in the header.
  var stardateOut = document.getElementById('stardate-out');
  function updateStardate() {
    if (!stardateOut) return;
    var value = (document.getElementById('played_on') || {}).value;
    if (!value) { stardateOut.textContent = ''; return; }
    var parts = value.split('-');
    stardateOut.textContent = 'SD ' + parts[0].slice(2) + parts[1] + '.' + parts[2];
  }

  // ---------------------------------------------------------------------
  // Scoresheet scanning
  // ---------------------------------------------------------------------

  var scanButton = document.getElementById('scan-button');
  var photoInput = document.getElementById('photo');
  var status = document.getElementById('scan-status');

  function setStatus(message, kind) {
    if (!status) return;
    status.textContent = message || '';
    status.className = 'scan-status' + (kind ? ' scan-status-' + kind : '');
  }

  function setField(id, value) {
    if (value === null || value === undefined) return;
    var el = document.getElementById(id);
    if (el) el.value = value;
  }

  // Match a scanned name against the dropdown, ignoring case. If it is not on
  // the list, drop into the add field rather than silently discarding it.
  function setCaptain(field, value) {
    if (!value) return;
    var select = document.getElementById(field);
    if (!select) return;

    var wanted = value.trim().toLowerCase();
    var options = select.querySelectorAll('option');
    for (var i = 0; i < options.length; i++) {
      if (options[i].value.toLowerCase() === wanted) {
        select.value = options[i].value;
        toggleAddField(select);
        return;
      }
    }

    select.value = '__new__';
    toggleAddField(select);
    var typed = document.querySelector('input[name="' + field + '_new"]');
    if (typed) typed.value = value.trim();
  }

  function toggleAddField(select) {
    var panel = document.getElementById(select.dataset.target);
    if (!panel) return;
    var adding = select.value === '__new__';
    panel.hidden = !adding;
    var typed = panel.querySelector('input[type="text"]');
    if (typed) typed.required = adding;
    if (!adding && typed) typed.value = '';
  }

  function setRadio(name, value) {
    if (!value) return;
    var el = form.querySelector('input[name="' + name + '"][value="' + value + '"]');
    if (el) el.checked = true;
  }

  function fill(data) {
    setCaptain('player_captain', data.player_captain);
    setCaptain('bot_captain', data.bot_captain);
    setField('bot_difficulty', data.bot_difficulty);
    setRadio('board_side', data.board_side);

    if (data.player) {
      PLAYER_KEYS.forEach(function (key) { setField('p_' + key, data.player[key]); });
    }
    if (data.bot) {
      BOT_KEYS.forEach(function (key) { setField('b_' + key, data.bot[key]); });
    }

    applyBoardSide();
    recalculate();

    if (data.warnings && data.warnings.length) {
      setStatus('Filled in. ' + data.warnings.join(' ') + ' Check before saving.', 'warn');
    } else {
      setStatus('Filled in from the photo. Check it, then save.', 'ok');
    }
  }

  if (scanButton && photoInput) {
    scanButton.addEventListener('click', function () { photoInput.click(); });

    photoInput.addEventListener('change', function () {
      if (!photoInput.files || !photoInput.files[0]) return;

      var body = new FormData();
      body.append('photo', photoInput.files[0]);

      scanButton.disabled = true;
      scanButton.classList.add('is-busy');
      setStatus('Reading the sheet', 'busy');

      fetch('/api/extract', { method: 'POST', body: body })
        .then(function (response) {
          return response.json().then(function (data) {
            if (!response.ok) throw new Error(data.error || 'Could not read that photo.');
            return data;
          });
        })
        .then(fill)
        .catch(function (error) {
          setStatus(error.message + ' Fill it in by hand instead.', 'error');
        })
        .then(function () {
          scanButton.disabled = false;
          scanButton.classList.remove('is-busy');
        });
    });
  }

  Array.prototype.forEach.call(
    document.querySelectorAll('.captain-select'), toggleAddField);
  applyBoardSide();
  applyEnding();
  recalculate();
  updateStardate();
})();
