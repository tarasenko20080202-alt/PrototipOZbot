const tg = window.Telegram?.WebApp;
if (tg) { tg.ready(); tg.expand(); }

const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];

// Даты: реальные дни недели и локальная дата (а не UTC)
const dateRow = $('#dateRow');
const pad = (n) => String(n).padStart(2, '0');
const localISO = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const base = new Date();
for (let i = 0; i < 5; i++) {
  const d = new Date(base); d.setDate(base.getDate() + i);
  const label = i === 0 ? 'сегодня' : i === 1 ? 'завтра' : d.toLocaleDateString('ru-RU', { weekday: 'short' });
  const b = document.createElement('button');
  b.className = 'date' + (i === 0 ? ' selected' : '');
  b.dataset.date = localISO(d);
  b.innerHTML = `<strong>${pad(d.getDate())}</strong><small>${label}</small>`;
  dateRow.appendChild(b);
}

function openTab(name) {
  const tab = $(`.tab[data-tab="${name}"]`);
  if (!tab) return;
  $$('.tab').forEach(x => x.classList.remove('active'));
  $$('.panel').forEach(x => x.classList.remove('active'));
  tab.classList.add('active');
  $('#' + name).classList.add('active');
}

$$('.tab').forEach(tab => tab.addEventListener('click', () => openTab(tab.dataset.tab)));

// Бот открывает Mini App сразу на нужной вкладке: ?tab=works
openTab(new URLSearchParams(location.search).get('tab') || '');

$$('.choice').forEach(x => x.addEventListener('click', () => {
  $$('.choice').forEach(c => c.classList.remove('selected'));
  x.classList.add('selected');
}));

$$('.date').forEach(x => x.addEventListener('click', () => {
  $$('.date').forEach(d => d.classList.remove('selected'));
  x.classList.add('selected');
}));

$$('.time').forEach(x => x.addEventListener('click', () => {
  $$('.time').forEach(t => t.classList.remove('selected'));
  x.classList.add('selected');
}));

function toast(msg) {
  const el = $('#toast'); el.textContent = msg; el.classList.add('show');
  setTimeout(() => el.classList.remove('show'), 2400);
}

let sending = false;
$('#submit').addEventListener('click', async () => {
  if (sending) return;
  const name = $('#name').value.trim();
  const comment = $('#comment').value.trim();
  const service = $('.choice.selected')?.dataset.service || 'Татуировка';
  const date = $('.date.selected')?.dataset.date || '';
  const time = $('.time.selected')?.dataset.time || '';
  if (!name || !comment) { toast('Заполни имя и описание задумки'); return; }

  if (!tg || !tg.initData) {            // открыто не из Telegram (отладка в браузере)
    toast('Данные готовы к отправке');
    console.log({ action: 'booking_request', name, comment, service, date, time });
    return;
  }

  // Отправляем заявку на сервер: так работает при запуске и с inline-кнопки,
  // и с нижней кнопки (tg.sendData работает только с нижней).
  sending = true;
  $('#submit').disabled = true;
  try {
    const r = await fetch('/api/booking', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ initData: tg.initData, name, comment, service, date, time }),
    });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    toast('Заявка отправлена');
    setTimeout(() => tg.close(), 900);
  } catch (e) {
    console.error(e);
    sending = false;
    $('#submit').disabled = false;
    toast('Не получилось отправить. Напиши в чат с ботом');
  }
});
