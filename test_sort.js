// Exercise the record table's client-side sorting against a real DOM.
const fs = require('fs');
const { JSDOM } = require('jsdom');

const html = fs.readFileSync('/home/claude/captains-log/templates/stats.html', 'utf8');
const js = fs.readFileSync('/home/claude/captains-log/static/stats.js', 'utf8');

const rows = [
  { captain: 'Georgiou', wins: 5, losses: 3, percent: 63, average: 74, best: 94 },
  { captain: 'Kirk',     wins: 3, losses: 1, percent: 75, average: 71, best: 82 },
  { captain: 'Soval',    wins: 1, losses: 1, percent: 50, average: 66, best: 70 },
  { captain: 'Ahab',     wins: 1, losses: 0, percent: 100, average: null, best: null },
];

// Reproduce the table markup the template emits.
const body = rows.map(r => `
  <tr data-captain="${r.captain}" data-wins="${r.wins}" data-percent="${r.percent}"
      data-average="${r.average ?? ''}" data-best="${r.best ?? ''}">
    <td class="led-name"><a>${r.captain}</a></td>
    <td>${r.wins}-${r.losses}</td><td>${r.percent}%</td>
    <td>${r.average ?? '—'}</td><td>${r.best ?? '—'}</td>
  </tr>`).join('');

const head = ['captain|text|Captain', 'wins|number|W-L', 'percent|number|Rate',
              'average|number|Avg', 'best|number|Best']
  .map(spec => {
    const [key, type, label] = spec.split('|');
    const sorted = key === 'wins' ? ' is-sorted' : '';
    return `<th aria-sort="${key === 'wins' ? 'descending' : 'none'}">
      <button class="led-sort${sorted}" data-key="${key}" data-type="${type}">${label}</button></th>`;
  }).join('');

const dom = new JSDOM(`<!DOCTYPE html><body>
  <form id="filters"><details class="picker"><div class="picker-actions">
    <button data-pick="all">All</button><button data-pick="none">None</button>
  </div><input type="checkbox"></details></form>
  <table id="record-table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>
</body>`, { runScripts: 'outside-only' });

dom.window.eval(js);
const doc = dom.window.document;

let failures = [];
function check(label, cond, detail = '') {
  if (cond) console.log(`  ok   ${label}`);
  else { console.log(`  FAIL ${label} ${detail}`); failures.push(label); }
}

const order = () => Array.from(doc.querySelectorAll('#record-table tbody tr'))
  .map(r => r.getAttribute('data-captain'));
const click = key => doc.querySelector(`.led-sort[data-key="${key}"]`).click();
const sortedKey = () => doc.querySelector('.led-sort.is-sorted')?.dataset.key;
const isAsc = () => doc.querySelector('.led-sort.is-sorted')?.classList.contains('is-ascending');

console.log('\nsorting');
check('starts on wins', sortedKey() === 'wins');

click('percent');
check('rate sorts high to low first', order()[0] === 'Ahab', order().join(','));
check('indicator moves', sortedKey() === 'percent' && !isAsc());

click('percent');
check('second click reverses', order()[0] === 'Soval', order().join(','));
check('ascending flagged', isAsc() === true);

click('captain');
check('names start A to Z', order()[0] === 'Ahab', order().join(','));
check('text defaults ascending', isAsc() === true);
click('captain');
check('names reverse to Z to A', order()[0] === 'Soval', order().join(','));

click('average');
check('blank averages sort last', order()[order().length - 1] === 'Ahab', order().join(','));
click('average');
check('blanks stay last when reversed',
      order()[order().length - 1] === 'Ahab', order().join(','));

click('wins');
check('wins high to low', order().join(',') === 'Georgiou,Kirk,Ahab,Soval',
      order().join(','));

console.log('\ntie breaking');
check('equal wins fall back to name',
      order().indexOf('Ahab') < order().indexOf('Soval'), order().join(','));

console.log('\naria');
const th = doc.querySelector('.led-sort[data-key="wins"]').closest('th');
check('active header announces its direction', th.getAttribute('aria-sort') === 'descending',
      th.getAttribute('aria-sort'));
const other = doc.querySelector('.led-sort[data-key="best"]').closest('th');
check('inactive headers announce none', other.getAttribute('aria-sort') === 'none');
check('only one header marked',
      doc.querySelectorAll('.led-sort.is-sorted').length === 1);

console.log('\nrow integrity');
check('no rows lost', order().length === 4);
check('no duplicates', new Set(order()).size === 4);

console.log();
if (failures.length) { console.log(`${failures.length} failed: ${failures.join(', ')}`); process.exit(1); }
console.log('all checks passed');
