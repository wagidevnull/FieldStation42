const params = new URLSearchParams(window.location.search);
const THEME = params.get('theme') || '80s';
const SLOT_COUNT = parseInt(params.get('slots')) || 3;
const HEADER_TEXT = params.get('header') || null;
const PAUSE_OVERRIDE = params.get('pause');
const MOCK = params.get('mock') === '1';
const USE_META = params.get('use_meta') !== '0';
const SHOW_DESCRIPTION = ['1', 'true'].includes((params.get('show_description') || '').toLowerCase());
const MUSIC_PATH = params.get('music');
const VIDEOS = params.get('videos') !== 'false';
const MESSAGES_PATH = params.get('messages');
const LOOP = params.get('loop') !== '0';
let RANDOM_START = params.get('random_start') === '1';
const INTERACTIVE = params.get('interactive') === '1';
const AUTOSCROLL = params.get('autoscroll') !== '0';
const PREVIEW = params.get('preview') === '1';
const VIDEO_SIDE = params.get('video_side');
const LOGO = params.get('logo');
// a second logo at the top right of the info panel, beside the preview (e.g. TV Guide)
const BRAND = params.get('brand');
const NAV_IDLE_MS = (parseInt(params.get('nav_timeout')) || 15) * 1000;
// the channel the guide was opened from (added by the player) - it starts selected
const CURRENT_CHANNEL = params.get('current');

let stations = [];
let gridSchedules = {};

// list-mode scroll state
let animFrame = null;
let scrollY = 0;
let pauseUntil = 0;

// grid-mode scroll state
let gridAnimFrame = null;
let gridScrollY = 0;
let gridPauseUntil = 0;

// music
let musicPlaylist = [];
let currentMusicIndex = 0;
let bgPlayer = null;

// video
let videoPlaylist = [];
let currentVideoIndex = 0;
let bgVideoPlayer = null;

// text carousel
let messages = [];
let messageCarouselTimer = null;

// interactive navigation
let navActive = false;
let navIndex = 0;
let navTime = Date.now();   // the selected program is whichever covers this moment
let gridSlotOffset = 0;     // half-hour slots the grid has been paged forward
let navBusy = false;
let navIdleTimer = null;
let navTuning = false;

// auto-tune: programs the player switches to as they begin (see /autotune)
let autotunes = [];
let autotuneDialog = null;   // {station, block, options, cursor} while the menu is up
let autotuneToastTimer = null;


function loadTheme(name, fallback = true) {
  return new Promise(function (resolve) {
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = 'themes/' + name + '.css';
    link.addEventListener('load', resolve);
    link.addEventListener('error', function () {
      if (!fallback) {
        console.warn('theme "' + name + '" not found.');
        resolve();
        return;
      }
      console.warn('theme "' + name + '" not found, falling back to 80s.');
      if (name !== '80s') {
        loadTheme('80s').then(resolve);
      } else {
        resolve();
      }
    });
    document.head.appendChild(link);
  });
}

function getCSSVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

// Switches a look can flip in its CSS (all off unless the look sets them):
//   --time-style: short     5:30a rather than 5:30 PM, like a satellite box
//   --grid-stub: date       the time bar's corner shows the date, not the clock
//   --channel-label: name   channels by name (call_sign if the config has one), no logos
//   --grid-snap: rows       the grid scrolls by whole rows - none cut in half at the edges
const lookFlag = name => getCSSVar(name).replace(/["']/g, '').trim();

function formatTime12(date) {
  if (lookFlag('--time-style') === 'short') {
    const h = date.getHours();
    return `${h % 12 || 12}:${String(date.getMinutes()).padStart(2, '0')}${h < 12 ? 'a' : 'p'}`;
  }
  return date.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });
}

function formatDateForAPI(date) {
  const y = date.getFullYear();
  const mo = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  const h = String(date.getHours()).padStart(2, '0');
  const mi = String(date.getMinutes()).padStart(2, '0');
  const s = String(date.getSeconds()).padStart(2, '0');
  return `${y}-${mo}-${d}T${h}:${mi}:${s}`;
}

function getPauseDuration() {
  if (PAUSE_OVERRIDE) return parseFloat(PAUSE_OVERRIDE) * 1000;
  const match = getCSSVar('--scroll-pause').match(/([\d.]+)\s*s/);
  return match ? parseFloat(match[1]) * 1000 : 5000;
}

function getScrollSpeed() {
  const val = parseFloat(getCSSVar('--scroll-speed'));
  return (!isNaN(val) && val > 0) ? val : 1.1;
}

function computeSlotTimes() {
  const now = new Date();
  const base = new Date(now.getFullYear(), now.getMonth(), now.getDate(),
    now.getHours(), Math.floor(now.getMinutes() / 30) * 30 + gridSlotOffset * 30, 0, 0);
  const slots = [];
  for (let i = 0; i < SLOT_COUNT; i++) {
    const start = new Date(base.getTime() + i * 30 * 60 * 1000);
    slots.push({ start, end: new Date(start.getTime() + 30 * 60 * 1000) });
  }
  return slots;
}

// mock data for local scroll testing (?mock=1)
const MOCK_SHOWS = [
  'Late Night Movie', 'The Evening News', 'Sports Center', 'Nature Documentary',
  'Sitcom Reruns', 'Talk Show', 'Crime Drama', 'Cooking Hour', 'Saturday Morning Cartoons',
  'Local Weather Update', 'Classic Film', 'Music Videos', 'Game Show Marathon',
  'Science Fiction Theater', 'Western Double Feature', 'Home Shopping', 'News Magazine',
  'Children\'s Programming', 'Live Sports', 'Comedy Special'
];

function mockFetchStations() {
  stations = Array.from({ length: 24 }, function (_, i) {
    const num = i + 2;
    return {
      channel_number: num,
      network_name: 'ch' + num,
      network_long_name: 'Channel ' + num,
      has_schedule: true
    };
  });
}

function mockFetchAllSchedules(slots) {
  const schedules = {};
  const slotMs = 30 * 60 * 1000;
  for (const station of stations) {
    const blocks = [];
    let t = slots[0].start.getTime();
    const end = slots[slots.length - 1].end.getTime();
    while (t < end) {
      const duration = (Math.floor(Math.random() * 3) + 1) * slotMs;
      const title = MOCK_SHOWS[Math.floor(Math.random() * MOCK_SHOWS.length)];
      blocks.push({ start_time: new Date(t).toISOString(), end_time: new Date(t + duration).toISOString(), title });
      t += duration;
    }
    schedules[station.network_name] = blocks;
  }
  return schedules;
}

async function fetchStations() {
  const all = await window.fs42Common.fetchChannels();
  stations = all.filter(s => !s.hidden);
}

async function fetchAllSchedules(slots, includeMeta) {
  if (!stations.length) return {};

  const overallStart = slots[0].start;
  const overallEnd = slots[slots.length - 1].end;

  try {
    return await window.fs42Common.fetchGuideSchedules(
      formatDateForAPI(overallStart),
      formatDateForAPI(overallEnd),
      includeMeta
    );
  } catch (e) {
    console.error('error fetching schedules', e);
    return {};
  }
}


// ===== LIST MODE (80s) =====

function findBlockForSlot(blocks, slotStart) {
  for (const block of blocks) {
    const bStart = new Date(block.start_time);
    const bEnd = new Date(block.end_time);
    if (bStart <= slotStart && bEnd > slotStart) {
      return { block, continued: bStart < slotStart };
    }
  }
  return null;
}

function buildScrollStrip(slots, schedules) {
  const strip = document.createElement('div');
  strip.id = 'guide-scroll-strip';

  const channelAfter = getCSSVar('--channel-position').replace(/["']/g, '') === 'after';
  const offairText = getCSSVar('--offair-text').replace(/^["']|["']$/g, '') || 'Offair';

  for (const slot of slots) {
    const heading = document.createElement('div');
    heading.className = 'time-slot-heading';
    heading.textContent = formatTime12(slot.start);
    strip.appendChild(heading);

    for (const station of stations) {
      const row = document.createElement('div');
      row.className = 'listing-row';
      if (channelAfter) row.classList.add('channel-after');

      const channelInfo = document.createElement('span');
      channelInfo.className = 'channel-info';

      const numSpan = document.createElement('span');
      numSpan.className = 'channel-number';
      numSpan.textContent = station.channel_number || '?';

      const nameSpan = document.createElement('span');
      nameSpan.className = 'channel-name';
      const name = station.network_name;
      nameSpan.textContent = name.length > 10 ? name.slice(0, 10) + '…' : name;

      channelInfo.appendChild(numSpan);
      channelInfo.appendChild(nameSpan);

      const titleSpan = document.createElement('span');
      titleSpan.className = 'show-title';

      const result = findBlockForSlot(schedules[station.network_name] || [], slot.start);
      if (result) {
        const t = result.block.title || offairText;
        titleSpan.textContent = t.length > 20 ? t.slice(0, 20) + '…' : t;
        if (result.continued) row.classList.add('continued');
      } else {
        titleSpan.textContent = offairText;
      }

      row.appendChild(channelInfo);
      row.appendChild(titleSpan);
      strip.appendChild(row);
    }
  }

  return strip;
}

function stopScrolling() {
  if (animFrame) {
    cancelAnimationFrame(animFrame);
    animFrame = null;
  }
}

async function buildGuide() {
  const slots = computeSlotTimes();
  const schedules = MOCK ? mockFetchAllSchedules(slots) : await fetchAllSchedules(slots);
  const listings = document.getElementById('guide-listings');
  listings.innerHTML = '';
  listings.appendChild(buildScrollStrip(slots, schedules));
}

function startScrolling() {
  stopScrolling();

  const listings = document.getElementById('guide-listings');
  const strip = document.getElementById('guide-scroll-strip');
  if (!strip) return;

  const pxPerMs = getScrollSpeed() / 50;
  const pauseMs = getPauseDuration();

  scrollY = 0;
  strip.style.transform = 'translateY(0)';
  pauseUntil = performance.now() + pauseMs;

  let lastTime = null;

  function tick(now) {
    if (now < pauseUntil) {
      animFrame = requestAnimationFrame(tick);
      return;
    }

    const maxScroll = strip.offsetHeight - listings.clientHeight;

    if (maxScroll <= 0) {
      setTimeout(async function () { await buildGuide(); startScrolling(); }, pauseMs);
      return;
    }

    if (lastTime !== null) scrollY += pxPerMs * (now - lastTime);
    lastTime = now;

    if (scrollY >= maxScroll) {
      strip.style.transform = `translateY(-${maxScroll}px)`;
      lastTime = null;
      setTimeout(async function () { await buildGuide(); startScrolling(); }, pauseMs);
      return;
    }

    strip.style.transform = `translateY(-${scrollY}px)`;
    animFrame = requestAnimationFrame(tick);
  }

  animFrame = requestAnimationFrame(tick);
}


// A channel's logo (channel_logo in its config) stands in for its name when it has one
function channelNameOrLogo(station) {
  if (lookFlag('--channel-label') === 'name') {
    const nameSpan = document.createElement('span');
    nameSpan.className = 'channel-name';
    nameSpan.textContent = station.call_sign || station.network_name;
    return nameSpan;
  }
  if (station.channel_logo) {
    const img = document.createElement('img');
    img.className = 'channel-logo';
    img.src = station.channel_logo;
    img.alt = station.network_name;
    return img;
  }
  const nameSpan = document.createElement('span');
  nameSpan.className = 'channel-name';
  nameSpan.textContent = station.network_name;
  return nameSpan;
}

// ===== GRID MODE (90s / 00s) =====

function buildGridDOM() {
  const listings = document.getElementById('guide-listings');
  listings.classList.add('grid-mode');
  // interactive guides use the text panel to describe the selected channel
  const textPanel = INTERACTIVE ? `
      <div id="text-panel" class="info-mode">
        <div id="info-top">
          <div id="info-logo"></div>
          <div id="info-right">
            <div id="info-weather" hidden><img alt=""><span id="info-temp"></span></div>
            <div id="info-datetime"><span id="info-day"></span><span id="info-time"></span></div>
            <div id="info-brand"></div>
          </div>
        </div>
        <div id="info-channel"></div>
        <div id="info-title"></div>
        <div id="info-episode"></div>
        <div id="info-times"></div>
        <div id="info-desc"></div>
      </div>` : `
      <div id="text-panel">
        <div id="text-message-title"></div>
        <div id="text-message-body"></div>
      </div>`;
  listings.innerHTML = `
    <div id="top-panel">
      <div id="video-panel"><video id="bgVideoPlayer" preload="auto"></video><div id="video-badge"></div></div>
      ${textPanel}
    </div>
    <div id="grid-wrapper">
      <div id="grid-header"><div class="grid-channel-stub"><span id="clock"></span></div></div>
      <div id="grid-listings"></div>
      <div id="guide-footer">
        <span class="footer-left">All Channels</span>
        <span class="footer-hints">
          <span><i class="dot red"></i>&#9664; Earlier</span>
          <span><i class="dot green"></i>Later &#9654;</span>
          <span><i class="dot yellow"></i>Select to Tune</span>
        </span>
      </div>
    </div>
  `;

  const videoSide = VIDEO_SIDE || getCSSVar('--video-side').replace(/["']/g, '') || 'left';
  if (videoSide === 'right') {
    document.getElementById('video-panel').style.order = '1';
    document.getElementById('text-panel').style.order = '0';
  }

  bgVideoPlayer = document.getElementById('bgVideoPlayer');
  // the number of the channel in the preview, for looks that show one on its frame
  document.getElementById('video-badge').textContent = CURRENT_CHANNEL || '';
}

function updateGridHeader(slots) {
  const header = document.getElementById('grid-header');
  if (!header) return;
  // Remove old slot labels, keep the channel stub
  const stub = header.querySelector('.grid-channel-stub');
  header.innerHTML = '';
  if (stub) {
    header.appendChild(stub);
  } else {
    const newStub = document.createElement('div');
    newStub.className = 'grid-channel-stub';
    header.appendChild(newStub);
  }
  for (const slot of slots) {
    const slotEl = document.createElement('div');
    slotEl.className = 'grid-time-slot';
    slotEl.textContent = formatTime12(slot.start);
    header.appendChild(slotEl);
  }
}

function createGridProgramBlock(block, guideStartMs, guideEndMs, totalMs, now) {
  const bStart = new Date(block.start_time);
  const bEnd = new Date(block.end_time);

  if (bEnd.getTime() <= guideStartMs || bStart.getTime() >= guideEndMs) return null;

  const visStart = Math.max(bStart.getTime(), guideStartMs);
  const visEnd = Math.min(bEnd.getTime(), guideEndMs);

  const leftPct = (visStart - guideStartMs) / totalMs * 100;
  const widthPct = (visEnd - visStart) / totalMs * 100;

  const el = document.createElement('div');
  el.className = 'grid-program-block';
  if (bStart <= now && bEnd > now) el.classList.add('current');
  el.dataset.start = bStart.getTime();
  el.dataset.end = bEnd.getTime();

  el.style.left = leftPct + '%';
  el.style.width = `calc(${widthPct}% - 2px)`;

  const titleSpan = document.createElement('span');
  titleSpan.className = 'program-title';
  titleSpan.textContent = block.title || 'Untitled';
  el.appendChild(titleSpan);

  const meta = USE_META && block.meta;
  let desc = meta && meta.plot;
  let isEpisodeTitle = false;
  if (meta && meta.type === 'episode' && !SHOW_DESCRIPTION && meta.title) {
    desc = meta.title;
    isEpisodeTitle = true;
  }
  if (desc) {
    const descSpan = document.createElement('span');
    descSpan.className = isEpisodeTitle ? 'program-desc is-episode-title' : 'program-desc';
    descSpan.textContent = desc;
    el.appendChild(descSpan);
  }

  return el;
}

function buildGridStrip(slots, schedules) {
  const strip = document.createElement('div');
  strip.id = 'grid-scroll-strip';

  const guideStartMs = slots[0].start.getTime();
  const guideEndMs = slots[slots.length - 1].end.getTime();
  const totalMs = guideEndMs - guideStartMs;
  const now = new Date();
  const offairText = getCSSVar('--offair-text').replace(/^["']|["']$/g, '') || 'No Info';

  for (const station of stations) {
    const row = document.createElement('div');
    row.className = 'grid-row';

    const channelDiv = document.createElement('div');
    channelDiv.className = 'grid-channel';

    const numSpan = document.createElement('span');
    numSpan.className = 'channel-number';
    numSpan.textContent = station.channel_number || '?';

    channelDiv.appendChild(numSpan);
    channelDiv.appendChild(channelNameOrLogo(station));
    row.appendChild(channelDiv);

    const programsDiv = document.createElement('div');
    programsDiv.className = 'grid-programs';

    const blocks = schedules[station.network_name] || [];

    if (!station.has_schedule || !blocks.length) {
      const noInfo = document.createElement('div');
      noInfo.className = 'grid-program-block';
      noInfo.style.left = '0';
      noInfo.style.width = '100%';
      const t = document.createElement('span');
      t.className = 'program-title';
      t.textContent = station.network_long_name || offairText;
      noInfo.appendChild(t);
      programsDiv.appendChild(noInfo);
    } else {
      for (const block of blocks) {
        const blockEl = createGridProgramBlock(block, guideStartMs, guideEndMs, totalMs, now);
        if (blockEl) programsDiv.appendChild(blockEl);
      }
    }

    row.appendChild(programsDiv);
    strip.appendChild(row);
  }

  return strip;
}

async function buildGrid() {
  const slots = computeSlotTimes();
  updateGridHeader(slots);
  const schedules = MOCK ? mockFetchAllSchedules(slots) : await fetchAllSchedules(slots, USE_META);
  gridSchedules = schedules;
  const gridListings = document.getElementById('grid-listings');
  // the new rows go in already scrolled to where the old ones were, and the cursor is
  // put back before anything else waits - otherwise the top channels flash up for a
  // moment before the selection scrolls back down
  const strip = buildGridStrip(slots, schedules);
  strip.style.transform = `translateY(-${gridScrollY}px)`;
  gridListings.replaceChildren(strip);
  fitGridRows();
  // a rebuild replaces the rows, so put the cursor back - never on something already aired
  navTime = Math.max(navTime, Date.now());
  if (navActive) applyNavSelection();
  else updateInfoPanel();
  if (INTERACTIVE) {
    await loadAutotunes();
    markAutotuneCells();
  }
}

function startGridScrolling() {
  // the viewer is driving - auto-scroll resumes when navigation goes idle
  if (navActive) return;

  if (!AUTOSCROLL) {
    // static guide - just hold the current position
    const strip = document.getElementById('grid-scroll-strip');
    if (strip) strip.style.transform = `translateY(-${gridScrollY}px)`;
    return;
  }

  if (gridAnimFrame) {
    cancelAnimationFrame(gridAnimFrame);
    gridAnimFrame = null;
  }

  const listings = document.getElementById('grid-listings');
  const strip = document.getElementById('grid-scroll-strip');
  if (!strip || !listings) return;

  const pxPerMs = getScrollSpeed() / 50;
  const pauseMs = getPauseDuration();

  // Clean up any previous clone
  const existingClone = document.getElementById('grid-scroll-strip-clone');
  if (existingClone) existingClone.remove();

  let clone;
  const originalHeight = strip.scrollHeight;

  // Loop guide if true.
  if (LOOP) {
    clone = strip.cloneNode(true);
    clone.id = 'grid-scroll-strip-clone';
    clone.setAttribute('aria-hidden', 'true');
    strip.parentElement.appendChild(clone);
    clone.style.transform = `translateY(${originalHeight}px)`;
  }
      // Random channel start
      if (RANDOM_START) {
        gridScrollY = Math.random() * originalHeight;
        RANDOM_START = false;
      } else if (!LOOP) {
        gridScrollY = 0;
      }
        
  strip.style.transform = 'translateY(0)';
  gridPauseUntil = LOOP ? 0 : performance.now() + pauseMs;

  let lastTime = null;

  function tick(now) {
    if (now < gridPauseUntil) {
      gridAnimFrame = requestAnimationFrame(tick);
      return;
    }

    // Loop guide if true.
    if (LOOP) {
      if (lastTime !== null) gridScrollY += pxPerMs * (now - lastTime);
      lastTime = now;

      if (gridScrollY >= originalHeight) {
        gridScrollY -= originalHeight;
        if (gridAnimFrame) {
          cancelAnimationFrame(gridAnimFrame);
          gridAnimFrame = null;
        }
        buildGrid().then(startGridScrolling);
        return;
      }

      strip.style.transform = `translateY(-${gridScrollY}px)`;
      clone.style.transform = `translateY(${originalHeight - gridScrollY}px)`;
      gridAnimFrame = requestAnimationFrame(tick);

    } else {
      const maxScroll = strip.offsetHeight - listings.clientHeight;

      if (maxScroll <= 0) {
        setTimeout(async function () { await buildGrid(); startGridScrolling(); }, pauseMs);
        return;
      }

      if (lastTime !== null) gridScrollY += pxPerMs * (now - lastTime);
      lastTime = now;

      if (gridScrollY >= maxScroll) {
        strip.style.transform = `translateY(-${maxScroll}px)`;
        lastTime = null;
        setTimeout(async function () { await buildGrid(); startGridScrolling(); }, pauseMs);
        return;
      }

      strip.style.transform = `translateY(-${gridScrollY}px)`;
      gridAnimFrame = requestAnimationFrame(tick);
    }
  }

  gridAnimFrame = requestAnimationFrame(tick);
}

// how many channels the grid shows at once (?rows= overrides): everything in the
// listings half is sized in em, so scaling its font size scales rows, logos and text
// together until exactly that many rows fill it
const GRID_ROWS = parseInt(params.get('rows'), 10) || 6;

function fitGridRows() {
  const wrapper = document.getElementById('grid-wrapper');
  const listings = document.getElementById('grid-listings');
  const row = document.querySelector('#grid-scroll-strip .grid-row');
  if (!wrapper || !listings || !row) return;
  // the time header grows with it, which shrinks the listings - a few passes settle it
  for (let i = 0; i < 4; i++) {
    const size = parseFloat(getComputedStyle(wrapper).fontSize);
    const want = listings.clientHeight / GRID_ROWS;
    if (Math.abs(row.offsetHeight - want) < 0.5) break;
    wrapper.style.fontSize = `${size * want / row.offsetHeight}px`;
  }
}

window.addEventListener('resize', fitGridRows);
window.addEventListener('fs42-aspect', fitGridRows);

async function initGridMode() {
  document.getElementById('guide-header').style.display = 'none';
  const oldClock = document.getElementById('clock');
  if (oldClock) oldClock.remove();
  buildGridDOM();
  startClock();


  const mediaLoaded = Promise.all([
    loadMusicPlaylist(),
    loadVideoPlaylist(),
    loadMessages()
  ]);

  if (MOCK) mockFetchStations(); else await fetchStations();
  if (INTERACTIVE) {
    setupInfoPanel();
    setupWeather();
  }
  await buildGrid();
  if (INTERACTIVE && !AUTOSCROLL) {
    // nothing scrolls, so the cursor stays up - start on the channel the guide was
    // opened from, or else the first channel with a schedule
    enterNavMode();
    const current = stations.findIndex(s => String(s.channel_number) === CURRENT_CHANNEL);
    navIndex = current >= 0 ? current : Math.max(0, stations.findIndex(s => s.has_schedule));
    applyNavSelection();
  }
  startGridScrolling();
  if (INTERACTIVE) document.addEventListener('keydown', handleNavKey);
  // scrolling is what normally triggers a rebuild, so a static guide refreshes on a timer
  if (!AUTOSCROLL) setInterval(async function () { await buildGrid(); startGridScrolling(); }, 60000);

  await mediaLoaded;
  setupMusic();
  setupVideo();
  startTextCarousel();
}


// ===== INTERACTIVE NAVIGATION (grid mode) =====
// the remote sends PageUp/PageDown/Enter to web channels; arrows are for keyboards

function gridRows() {
  const strip = document.getElementById('grid-scroll-strip');
  return strip ? Array.from(strip.querySelectorAll('.grid-row')) : [];
}

function firstVisibleRowIndex(rows) {
  if (!rows.length) return 0;
  const base = rows[0].offsetTop;
  const i = rows.findIndex(r => r.offsetTop - base + r.offsetHeight > gridScrollY);
  return i < 0 ? 0 : i;
}

function applyNavSelection() {
  const rows = gridRows();
  if (!rows.length) return;
  navIndex = ((navIndex % rows.length) + rows.length) % rows.length;
  rows.forEach((r, i) => r.classList.toggle('nav-selected', i === navIndex));
  // highlight just the selected program - the one the info panel describes
  document.querySelectorAll('.grid-program-block.nav-cell').forEach(b => b.classList.remove('nav-cell'));
  const cells = Array.from(rows[navIndex].querySelectorAll('.grid-program-block'));
  const cell = cells.find(b => +b.dataset.start <= navTime && +b.dataset.end > navTime) || cells[0];
  if (cell) cell.classList.add('nav-cell');

  // keep the selected row centered where possible
  const listings = document.getElementById('grid-listings');
  const strip = document.getElementById('grid-scroll-strip');
  const row = rows[navIndex];
  const top = row.offsetTop - rows[0].offsetTop;
  const maxScroll = Math.max(0, strip.offsetHeight - listings.clientHeight);
  gridScrollY = Math.min(Math.max(0, top - (listings.clientHeight - row.offsetHeight) / 2), maxScroll);
  if (lookFlag('--grid-snap') === 'rows' && row.offsetHeight) {
    // keep the selected row in view, whole rows only
    const rowH = row.offsetHeight;
    gridScrollY = Math.min(Math.round(gridScrollY / rowH) * rowH, Math.floor(maxScroll / rowH + 0.01) * rowH);
    if (top < gridScrollY) gridScrollY = top;
    if (top + rowH > gridScrollY + listings.clientHeight) gridScrollY = top + rowH - listings.clientHeight;
  }
  strip.style.transform = `translateY(-${gridScrollY}px)`;

  // the loop clone would show duplicate rows under the cursor
  const clone = document.getElementById('grid-scroll-strip-clone');
  if (clone) clone.remove();

  updateInfoPanel();
}

function enterNavMode() {
  navActive = true;
  if (gridAnimFrame) {
    cancelAnimationFrame(gridAnimFrame);
    gridAnimFrame = null;
  }
  navIndex = firstVisibleRowIndex(gridRows());
  navTime = Date.now();
}

async function exitNavMode() {
  navActive = false;
  clearTimeout(navIdleTimer);
  gridRows().forEach(r => r.classList.remove('nav-selected', 'nav-tuning'));
  document.querySelectorAll('.grid-program-block.nav-cell').forEach(b => b.classList.remove('nav-cell'));
  // page the grid back to now before scrolling resumes
  if (gridSlotOffset) {
    gridSlotOffset = 0;
    await buildGrid();
  }
  updateInfoPanel();
  startGridScrolling();
}

function blockAt(blocks, t) {
  return blocks.find(b => new Date(b.start_time).getTime() <= t && new Date(b.end_time).getTime() > t);
}

// step to the previous/next program on the selected channel, paging the grid
// forward or back a half hour at a time when the program is off its edge
async function moveNavTime(dir) {
  const station = stations[navIndex];
  const blocks = (station && gridSchedules[station.network_name]) || [];
  const cur = blockAt(blocks, navTime);
  if (!cur) return;

  const now = Date.now();
  if (dir > 0) {
    navTime = new Date(cur.end_time).getTime();
  } else {
    const prevEnd = new Date(cur.start_time).getTime();
    if (prevEnd <= now) return;   // nothing earlier that hasn't already aired
    const prev = blockAt(blocks, prevEnd - 1);
    navTime = Math.max(prev ? new Date(prev.start_time).getTime() : prevEnd - 1, now);
  }

  const slotMs = 30 * 60 * 1000;
  const startOffset = gridSlotOffset;
  let slots = computeSlotTimes();
  while (navTime >= slots[slots.length - 1].end.getTime()) {
    gridSlotOffset++;
    slots = computeSlotTimes();
  }
  while (gridSlotOffset > 0 && navTime < slots[0].start.getTime()) {
    gridSlotOffset--;
    slots = computeSlotTimes();
  }
  if (gridSlotOffset !== startOffset) {
    // the rebuild re-applies the selection
    await buildGrid();
  }
}

function resetNavIdle() {
  clearTimeout(navIdleTimer);
  // a static guide keeps its cursor - there's no scroll to go back to
  if (AUTOSCROLL) navIdleTimer = setTimeout(exitNavMode, NAV_IDLE_MS);
}

// ===== INFO PANEL (interactive grid mode) =====

function setupInfoPanel() {
  const logo = document.getElementById('info-logo');
  if (LOGO) {
    const img = document.createElement('img');
    img.src = LOGO;
    img.alt = '';
    logo.appendChild(img);
  } else {
    const themeHeader = getCSSVar('--header-text').replace(/["']/g, '');
    logo.textContent = HEADER_TEXT || themeHeader || 'TV Guide';
    logo.classList.add('text-logo');
  }
  applyProviderLogo(logo);

  if (BRAND) {
    const img = document.createElement('img');
    img.src = BRAND;
    img.alt = '';
    // a missing file just leaves the spot empty
    img.onerror = () => img.remove();
    document.getElementById('info-brand').appendChild(img);
  }
}

// Current conditions beside the clock - a 1992 Weather Channel icon with the
// temperature to its right - for the Weather ZIP Code setting. The server keeps
// them fresh for ten minutes, and says when the Weather Display setting is off.
const WEATHER_REFRESH_MS = 10 * 60 * 1000;

async function setupWeather() {
  if (MOCK) return;
  const box = document.getElementById('info-weather');
  async function update() {
    try {
      const data = await (await fetch('/weather')).json();
      if (!data.enabled) {
        box.hidden = true;
        return;
      }
      const img = box.querySelector('img');
      const src = `/static/weather/${encodeURIComponent(data.icon)}.gif`;
      // setting the same src again restarts the animation - only change it when it changes
      if (img.getAttribute('src') !== src) img.src = src;
      img.title = `${data.caption} - ${data.place}`;
      document.getElementById('info-temp').textContent = `${data.temp}°${data.unit}`;
      box.hidden = false;
    } catch (e) {
      console.warn('weather not loaded:', e);
    }
  }
  await update();
  setInterval(update, WEATHER_REFRESH_MS);
}

// The Provider Logo setting from the settings menu wins over the logo= in the URL.
// The server picks the file, so a Random setting shows a different one each time.
async function applyProviderLogo(holder) {
  if (MOCK) return;
  try {
    const data = await (await fetch('/settings/provider_logo/pick')).json();
    const file = data.file;
    if (!file) return;
    const img = document.createElement('img');
    img.src = `/static/customguide/logos/${encodeURIComponent(file)}`;
    img.alt = '';
    holder.classList.remove('text-logo');
    holder.replaceChildren(img);
  } catch (e) {
    console.warn('provider logo setting not loaded:', e);
  }
}

function formatEpisodeLine(meta) {
  if (!meta || meta.type !== 'episode') return '';
  const num = (meta.season != null && meta.episode != null) ? `S${meta.season} E${meta.episode}` : '';
  const title = meta.title ? `"${meta.title}"` : '';
  return [num, title].filter(Boolean).join('  ');
}

function updateInfoPanel() {
  const panel = document.getElementById('text-panel');
  if (!panel || !panel.classList.contains('info-mode')) return;

  const set = (id, text) => { document.getElementById(id).textContent = text || ''; };
  const station = navActive ? stations[navIndex] : null;
  if (!station) {
    set('info-channel', '');
    set('info-title', 'Press ▲ ▼ to browse channels');
    set('info-episode', '');
    set('info-times', '');
    set('info-desc', '');
    panel.classList.remove('has-desc');
    return;
  }

  const block = blockAt(gridSchedules[station.network_name] || [], navTime);
  const meta = USE_META && block && block.meta;

  const channelLine = document.getElementById('info-channel');
  if (channelLine) {
    channelLine.replaceChildren();
    if (station.channel_logo) {
      const img = document.createElement('img');
      img.src = station.channel_logo;
      img.alt = '';
      channelLine.appendChild(img);
    }
    channelLine.append(`${station.channel_number || ''}  ${station.network_name}`);
  }
  set('info-title', block ? (block.title || 'Untitled') : (station.network_long_name || 'No Info'));
  set('info-episode', formatEpisodeLine(meta));
  const dash = lookFlag('--time-style') === 'short' ? ' - ' : ' – ';
  const times = block ? `${formatTime12(new Date(block.start_time))}${dash}${formatTime12(new Date(block.end_time))}` : '';
  set('info-times', block && autotuneFor(station, block) ? `${times}   •   Auto-Tune set` : times);
  set('info-desc', meta && meta.plot);
  // a description needs room, so the rest of the panel steps down a size for it
  panel.classList.toggle('has-desc', Boolean(meta && meta.plot));
}

async function tuneToSelected() {
  const station = stations[navIndex];
  if (!station || navTuning) return;
  navTuning = true;
  const row = gridRows()[navIndex];
  if (row) row.classList.add('nav-tuning');
  try {
    await fetch('/player/channels/' + encodeURIComponent(station.channel_number));
  } catch (e) {
    console.warn('tune failed:', e.message);
  }
  // if the player didn't switch away, let the viewer try again
  setTimeout(function () {
    navTuning = false;
    gridRows().forEach(r => r.classList.remove('nav-tuning'));
  }, 3000);
}

// OK on what's on now tunes to it; on something later, offers to auto-tune to it
function selectProgram() {
  const station = stations[navIndex];
  const block = station && blockAt(gridSchedules[station.network_name] || [], navTime);
  if (block && new Date(block.start_time).getTime() > Date.now()) {
    openAutotuneDialog(station, block);
  } else {
    tuneToSelected();
  }
}


// ===== AUTO-TUNE (interactive grid mode) =====

async function loadAutotunes() {
  if (MOCK) return;
  try {
    autotunes = (await (await fetch('/autotune')).json()).autotunes || [];
  } catch (e) {
    console.warn('auto-tunes not loaded:', e.message);
  }
}

function autotuneFor(station, block) {
  const start = new Date(block.start_time).getTime();
  return autotunes.find(a => a.channel === Number(station.channel_number) && a.start === start);
}

// tag the program cells that have an auto-tune set
function markAutotuneCells() {
  gridRows().forEach((row, i) => {
    const station = stations[i];
    row.querySelectorAll('.grid-program-block').forEach(cell => {
      const set = Boolean(station) && autotunes.some(a =>
        a.channel === Number(station.channel_number) && a.start === Number(cell.dataset.start));
      cell.classList.toggle('autotune', set);
    });
  });
}

function openAutotuneDialog(station, block) {
  const existing = autotuneFor(station, block);
  const start = new Date(block.start_time);
  autotuneDialog = {
    station,
    block,
    existing,
    options: existing
      ? [{ label: 'Remove Auto-Tune', action: 'remove' }, { label: 'Keep Auto-Tune', action: 'close' }]
      : [{ label: `Auto-Tune at ${formatTime12(start)}`, action: 'set' }, { label: 'Cancel', action: 'close' }],
    cursor: 0,
  };

  const overlay = document.createElement('div');
  overlay.id = 'autotune-overlay';
  const box = document.createElement('div');
  box.id = 'autotune-dialog';

  const line = (cls, text) => {
    const el = document.createElement('div');
    el.className = cls;
    el.textContent = text;
    return el;
  };
  box.appendChild(line('at-heading', 'Auto-Tune'));

  const channel = document.createElement('div');
  channel.className = 'at-channel';
  if (station.channel_logo) {
    const img = document.createElement('img');
    img.src = station.channel_logo;
    img.alt = '';
    channel.appendChild(img);
  }
  channel.append(`${station.channel_number}  ${station.network_name}`);
  box.appendChild(channel);

  box.appendChild(line('at-title', block.title || 'Untitled'));
  const episode = formatEpisodeLine(USE_META && block.meta);
  if (episode) box.appendChild(line('at-episode', episode));
  const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  box.appendChild(line('at-times',
    `${days[start.getDay()]} ${start.getMonth() + 1}/${start.getDate()}   ` +
    `${formatTime12(start)} – ${formatTime12(new Date(block.end_time))}`));
  box.appendChild(line('at-question', existing
    ? 'Auto-Tune is set - the TV will switch to this channel when the show begins.'
    : 'Switch to this channel automatically when the show begins?'));

  const options = document.createElement('div');
  options.className = 'at-options';
  autotuneDialog.options.forEach((option, i) => {
    const el = line('at-option', option.label);
    el.addEventListener('click', () => {
      autotuneDialog.cursor = i;
      confirmAutotune();
    });
    options.appendChild(el);
  });
  box.appendChild(options);
  box.appendChild(line('at-hint', '▲▼ Choose     OK Confirm     ◀ Back'));

  overlay.appendChild(box);
  document.body.appendChild(overlay);
  document.body.classList.add('autotune-open');
  placeAutotuneDialog();
  renderAutotuneCursor();
}

// the menu covers the guide but not the preview, so it sits below the video panel
function placeAutotuneDialog() {
  const box = document.getElementById('autotune-dialog');
  const panel = document.getElementById('video-panel');
  if (!box || !panel) return;
  const below = panel.getBoundingClientRect().bottom;
  const room = window.innerHeight - below;
  box.style.top = `${below + Math.max(0, (room - box.offsetHeight) / 2)}px`;
}

function renderAutotuneCursor() {
  document.querySelectorAll('#autotune-dialog .at-option').forEach((el, i) => {
    el.classList.toggle('cursor', i === autotuneDialog.cursor);
  });
}

function closeAutotuneDialog() {
  autotuneDialog = null;
  const overlay = document.getElementById('autotune-overlay');
  if (overlay) overlay.remove();
  document.body.classList.remove('autotune-open');
}

function handleAutotuneKey(key) {
  const count = autotuneDialog.options.length;
  if (key === 'PageUp' || key === 'ArrowUp') {
    autotuneDialog.cursor = (autotuneDialog.cursor - 1 + count) % count;
    renderAutotuneCursor();
  } else if (key === 'PageDown' || key === 'ArrowDown') {
    autotuneDialog.cursor = (autotuneDialog.cursor + 1) % count;
    renderAutotuneCursor();
  } else if (key === 'Enter') {
    confirmAutotune();
  } else if (key === 'ArrowLeft' || key === 'Escape') {
    closeAutotuneDialog();
  }
  resetNavIdle();
}

async function confirmAutotune() {
  const { station, block, existing, options, cursor } = autotuneDialog;
  const action = options[cursor].action;
  closeAutotuneDialog();
  if (action === 'close') return;
  try {
    let res;
    if (action === 'set') {
      res = await fetch('/autotune', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          channel: Number(station.channel_number),
          start: new Date(block.start_time).getTime(),
          network_name: station.network_name,
          title: block.title || '',
        }),
      });
    } else {
      res = await fetch('/autotune/' + encodeURIComponent(existing.id), { method: 'DELETE' });
    }
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    autotunes = (await res.json()).autotunes || [];
    markAutotuneCells();
    updateInfoPanel();
    showAutotuneToast(action === 'set'
      ? `Auto-Tune set: ${block.title || 'program'} at ${formatTime12(new Date(block.start_time))}`
      : 'Auto-Tune removed');
  } catch (e) {
    console.warn('auto-tune change failed:', e.message);
    showAutotuneToast('Could not change Auto-Tune - try again');
  }
}

function showAutotuneToast(text) {
  let toast = document.getElementById('autotune-toast');
  if (!toast) {
    toast = document.createElement('div');
    toast.id = 'autotune-toast';
    document.body.appendChild(toast);
  }
  toast.textContent = text;
  toast.hidden = false;
  clearTimeout(autotuneToastTimer);
  autotuneToastTimer = setTimeout(() => { toast.hidden = true; }, 3500);
}

async function handleNavKey(e) {
  const up = e.key === 'PageUp' || e.key === 'ArrowUp';
  const down = e.key === 'PageDown' || e.key === 'ArrowDown';
  const left = e.key === 'ArrowLeft';
  const right = e.key === 'ArrowRight';
  const select = e.key === 'Enter';
  if (!up && !down && !left && !right && !select) return;
  e.preventDefault();
  if (autotuneDialog) {
    handleAutotuneKey(e.key);
    return;
  }
  // a page of the grid is still loading
  if (navBusy) return;

  navBusy = true;
  try {
    if (!navActive) {
      // first press just brings up the cursor
      enterNavMode();
    } else if (up) {
      navIndex--;
    } else if (down) {
      navIndex++;
    } else if (left || right) {
      await moveNavTime(right ? 1 : -1);
    } else {
      selectProgram();
    }
    applyNavSelection();
    resetNavIdle();
  } finally {
    navBusy = false;
  }
}


// ===== CLOCK =====

function startClock() {
  const el = document.getElementById('clock');
  const tick = () => {
    const now = new Date();
    el.textContent = lookFlag('--grid-stub') === 'date'
      ? `${now.toLocaleDateString('en-US', { weekday: 'short' })} ${now.getMonth() + 1}/${now.getDate()}`
      : formatTime12(now);
    const day = document.getElementById('info-day');
    if (day) {
      day.textContent = lookFlag('--time-style') === 'short'
        ? now.toLocaleDateString('en-US', { weekday: 'short' })
        : now.toLocaleDateString('en-US', { weekday: 'short', month: 'numeric', day: 'numeric' }).toUpperCase();
      document.getElementById('info-time').textContent = formatTime12(now);
    }
  };
  tick();
  setInterval(tick, 1000);
}


// ===== RANDOM PLAYBACK =====

function randomOtherIndex(playlist, current) {
  if (playlist.length <= 1) return 0;
  let next;
  do { next = Math.floor(Math.random() * playlist.length); } while (next === current);
  return next;
}


// ===== MUSIC =====

async function loadMusicPlaylist() {
  try {
    if (MUSIC_PATH) {
      const resp = await fetch('/media/list?path=' + encodeURIComponent(MUSIC_PATH));
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      const data = await resp.json();
      musicPlaylist = data.files || [];
    } else {
      // Only fall back to the bundled json if the theme allows it
      const autoload = getCSSVar('--music-autoload').replace(/["']/g, '');
      if (autoload === 'false') return;
      const resp = await fetch('music_playlist.json');
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      const data = await resp.json();
      musicPlaylist = data.music_files || [];
    }
  } catch (e) {
    console.warn('no music playlist:', e.message);
  }
}

function playMusicTrack(index) {
  if (!bgPlayer || !musicPlaylist.length) return;
  currentMusicIndex = index % musicPlaylist.length;
  bgPlayer.src = musicPlaylist[currentMusicIndex];
  bgPlayer.play().catch(function () {
    document.addEventListener('click', () => bgPlayer.play(), { once: true });
  });
}

function setupMusic() {
  bgPlayer = document.getElementById('bgMusicPlayer');
  if (!bgPlayer || !musicPlaylist.length) return;

  const vol = parseFloat(getCSSVar('--music-volume'));
  bgPlayer.volume = isNaN(vol) ? 0.3 : vol;
  bgPlayer.addEventListener('ended', () => playMusicTrack(randomOtherIndex(musicPlaylist, currentMusicIndex)));
  bgPlayer.addEventListener('error', () => playMusicTrack(randomOtherIndex(musicPlaylist, currentMusicIndex)));
  playMusicTrack(Math.floor(Math.random() * musicPlaylist.length));
}


// ===== VIDEO =====

async function loadVideoPlaylist() {
  if (!VIDEOS || PREVIEW) return;
  try {
    const resp = await fetch('/media/list_videos');
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    const data = await resp.json();
    videoPlaylist = data.files || [];
  } catch (e) {
    console.warn('no video playlist:', e.message);
  }
}

function playVideoTrack(index) {
  if (!bgVideoPlayer || !videoPlaylist.length) return;
  currentVideoIndex = index % videoPlaylist.length;
  bgVideoPlayer.src = videoPlaylist[currentVideoIndex];
  bgVideoPlayer.play().catch(function (e) {
    console.warn('video play failed:', e.message);
  });
}

// The player keeps the current channel running in mpv and parks its window
// over the video panel, so the page only has to say where the panel is.
// Only the player's own browser reports, so a guide open elsewhere can't move it.
function reportPreviewRect() {
  const panel = document.getElementById('video-panel');
  if (!panel || MOCK || !navigator.userAgent.includes('FieldStation42-WebRender')) return;
  const box = panel.getBoundingClientRect();
  // a theme can frame the video (Halloween's slime) - the picture goes in the frame's opening
  const inset = name => parseFloat(getCSSVar(name)) || 0;
  const ix = box.width * inset('--video-inset-x');
  const r = {
    left: box.left + ix,
    top: box.top + box.height * inset('--video-inset-top'),
    width: box.width - 2 * ix,
    height: box.height * (1 - inset('--video-inset-top') - inset('--video-inset-bottom')),
  };
  const dpr = window.devicePixelRatio || 1;
  fetch('/player/guide/preview', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      x: Math.round((window.screenX + r.left) * dpr),
      y: Math.round((window.screenY + r.top) * dpr),
      width: Math.round(r.width * dpr),
      height: Math.round(r.height * dpr)
    })
  }).catch(function (e) {
    console.warn('preview rect failed:', e.message);
  });
}

function setupVideo() {
  bgVideoPlayer = document.getElementById('bgVideoPlayer');
  if (!bgVideoPlayer) return;

  if (PREVIEW) {
    document.getElementById('video-panel').style.background = '#000';
    reportPreviewRect();
    window.addEventListener('resize', reportPreviewRect);
    // the panel moves when the page is re-laid out for a different screen shape
    window.addEventListener('fs42-aspect', reportPreviewRect);
    return;
  }

  if (!videoPlaylist.length) {
    const videoPanel = document.getElementById('video-panel');
    if (videoPanel) videoPanel.style.display = 'none';
    return;
  }

  const vol = parseFloat(getCSSVar('--video-volume'));
  bgVideoPlayer.volume = isNaN(vol) ? 0.8 : vol;

  let consecutiveErrors = 0;

  bgVideoPlayer.addEventListener('ended', function () {
    consecutiveErrors = 0;
    playVideoTrack(randomOtherIndex(videoPlaylist, currentVideoIndex));
  });

  bgVideoPlayer.addEventListener('error', function () {
    consecutiveErrors++;
    if (consecutiveErrors >= videoPlaylist.length) {
      console.warn('all video tracks failed to load, hiding video panel');
      const videoPanel = document.getElementById('video-panel');
      if (videoPanel) videoPanel.style.display = 'none';
      return;
    }
    setTimeout(() => playVideoTrack(randomOtherIndex(videoPlaylist, currentVideoIndex)), 1000);
  });

  playVideoTrack(Math.floor(Math.random() * videoPlaylist.length));
}


// ===== TEXT CAROUSEL =====

async function loadMessages() {
  if (!MESSAGES_PATH) return;
  try {
    const resp = await fetch('/media/json?path=' + encodeURIComponent(MESSAGES_PATH));
    if (!resp.ok) throw new Error('HTTP ' + resp.status);
    const data = await resp.json();
    messages = data.messages || [];
  } catch (e) {
    console.warn('no messages:', e.message);
  }
}

function showNextMessage(index) {
  const titleEl = document.getElementById('text-message-title');
  const bodyEl = document.getElementById('text-message-body');
  if (!titleEl || !bodyEl) return;

  const msg = messages[index % messages.length];

  titleEl.style.opacity = '0';
  bodyEl.style.opacity = '0';

  setTimeout(function () {
    titleEl.innerHTML = msg.title || '';
    bodyEl.textContent = msg.body || '';
    titleEl.style.opacity = '1';
    bodyEl.style.opacity = '1';
  }, 400);

  const defaultDuration = parseFloat(getCSSVar('--text-carousel-speed')) || 10;
  const duration = ((msg.duration || defaultDuration) * 1000) + 400;
  messageCarouselTimer = setTimeout(function () {
    showNextMessage(index + 1);
  }, duration);
}

function startTextCarousel() {
  const titleEl = document.getElementById('text-message-title');
  const bodyEl = document.getElementById('text-message-body');
  if (!titleEl || !bodyEl) return;

  if (!messages.length) {
    titleEl.textContent = 'FieldStation42';
    bodyEl.textContent = '';
    return;
  }

  showNextMessage(0);
}


// ===== INIT =====

// A seasonal look is laid over the base theme: the Guide Theme setting, or with
// Seasonal Themes on, the one for today's date (the server works out which).
// ?look= overrides the setting, which is handy for previewing one.
async function loadSeasonalLook() {
  let look = params.get('look');
  if (!look && !MOCK) {
    try {
      const data = await (await fetch('/settings')).json();
      look = data.guide_look || (data.values && data.values.guide_theme);
    } catch (e) {
      console.warn('guide theme setting not loaded:', e);
    }
  }
  if (look && look !== 'default' && /^[a-z0-9_-]+$/.test(look)) {
    await loadTheme(look, false);
  }
}

async function init() {
  await loadTheme(THEME);
  await loadSeasonalLook();

  const headerPos = getCSSVar('--header-position').replace(/["']/g, '');
  if (headerPos === 'bottom') document.getElementById('guide-wrapper').classList.add('header-bottom');

  const themeHeader = getCSSVar('--header-text').replace(/["']/g, '');
  document.getElementById('header-text').textContent = HEADER_TEXT || themeHeader || 'TV Guide';

  const layoutMode = getCSSVar('--layout-mode').replace(/["']/g, '') || 'list';

  if (layoutMode === 'grid') {
    await initGridMode();
  } else {
    startClock();
    const musicLoaded = loadMusicPlaylist();
    if (MOCK) mockFetchStations(); else await fetchStations();
    await buildGuide();
    startScrolling();
    await musicLoaded;
    setupMusic();
  }
}

document.addEventListener('DOMContentLoaded', init);
