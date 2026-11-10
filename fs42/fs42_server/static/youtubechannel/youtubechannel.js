// A YouTube playlist channel (fs42/youtube_channel.py). The server keeps the
// lineup - the same one the guide lists - and this page plays whatever it says
// is on now, starting part-way in, in YouTube's own embedded player.
// The channel comes from ?network=<network_name> in the station's web_url.

const params = new URLSearchParams(window.location.search);
const NETWORK = params.get('network') || '';
// how often to check the page is still showing what the lineup says
const SYNC_MS = 60 * 1000;

let player = null;
let currentId = null;
let advanceTimer = null;
// videos that wouldn't play here - the lineup's next video stands in for them
const broken = new Set();
// captions follow the Subtitles setting from the settings menu
let captionsOn = false;
// how long after a video starts playing YouTube's title and play/pause overlay take to fade
const COVER_MS = 3500;
let coverTimer = null;

// which game it is, shown in the bottom left for a while once the picture is up
const GAME_SECONDS = 10;
let pendingGame = null;
let gameTimer = null;

function showGame(game) {
  const box = document.getElementById('game');
  clearTimeout(gameTimer);
  box.classList.remove('showing');
  if (!game) return;
  document.getElementById('game-matchup').textContent = game.matchup;
  document.getElementById('game-date').textContent = game.date;
  document.getElementById('game-note').textContent = game.note;
  document.getElementById('game-date').hidden = !game.date;
  document.getElementById('game-note').hidden = !game.note;
  box.classList.add('showing');
  gameTimer = setTimeout(() => box.classList.remove('showing'), GAME_SECONDS * 1000);
}

function cover(on) {
  clearTimeout(coverTimer);
  coverTimer = null;
  document.getElementById('cover').hidden = !on;
}

function setStatus(text) {
  const el = document.getElementById('status');
  el.textContent = text;
  el.hidden = !text;
}

async function fetchNow(after) {
  let url = `/youtube/${encodeURIComponent(NETWORK)}/now`;
  if (after) url += `?after=${after}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

function play(entry) {
  currentId = entry.id;
  setStatus('');
  cover(true);
  // the caption waits for the cover to lift, so it isn't spent on a black screen
  showGame(null);
  pendingGame = entry.game;
  player.loadVideoById({ videoId: entry.id, startSeconds: Math.floor(entry.offset) });
  // move on when the lineup does, even if the video runs a little long or stalls
  clearTimeout(advanceTimer);
  advanceTimer = setTimeout(() => syncToNow(), entry.remaining * 1000 + 500);
}

// what's on now - or, if that's a video that won't play (or the one that just
// finished early), the next one in the lineup
async function scheduledEntry(skip) {
  let entry = await fetchNow();
  for (let i = 0; i < 5 && (broken.has(entry.id) || entry.id === skip); i++) {
    entry = await fetchNow(Date.now() / 1000 + entry.remaining);
  }
  return entry;
}

async function syncToNow(skip) {
  try {
    const entry = await scheduledEntry(skip);
    if (entry.id !== currentId || skip) play(entry);
  } catch (e) {
    console.warn('lineup not ready:', e.message);
    if (!currentId) setStatus('Loading…');
    clearTimeout(advanceTimer);
    advanceTimer = setTimeout(() => syncToNow(), 10000);
  }
}

async function onPlayerReady() {
  await loadCaptionSetting();
  player.unMute();
  player.setVolume(100);
  syncToNow();
  setInterval(() => syncToNow(), SYNC_MS);
}

async function loadCaptionSetting() {
  try {
    const data = await (await fetch('/settings')).json();
    captionsOn = Boolean(data.values && data.values.subtitles && data.values.subtitles !== 'off');
  } catch (e) {
    console.warn('settings not loaded:', e.message);
  }
}

// YouTube turns its own captions on for some videos - switch them to match the setting
function applyCaptions() {
  if (captionsOn) {
    player.loadModule('captions');
    player.setOption('captions', 'track', { languageCode: 'en' });
  } else {
    player.unloadModule('captions');
    player.unloadModule('cc');
  }
}

function onPlayerStateChange(e) {
  if (e.data === YT.PlayerState.PLAYING) {
    applyCaptions();
    if (!document.getElementById('cover').hidden && !coverTimer) {
      coverTimer = setTimeout(() => {
        coverTimer = null;
        cover(false);
        if (pendingGame) showGame(pendingGame);
        pendingGame = null;
      }, COVER_MS);
    }
  }
  // a stand-in video can finish before its slot - go on to the next rather than replay it
  if (e.data === YT.PlayerState.ENDED) syncToNow(currentId);
}

function onPlayerError(e) {
  // a video that can't play here (embedding off, removed) - show the next one early
  console.warn('video error', e.data, '- skipping', currentId);
  broken.add(currentId);
  syncToNow();
}

// called by the YouTube IFrame API script once it has loaded
function onYouTubeIframeAPIReady() {
  if (!NETWORK) {
    setStatus('No channel set for this page');
    return;
  }
  player = new YT.Player('player', {
    width: '100%',
    height: '100%',
    playerVars: {
      autoplay: 1,
      controls: 0,
      disablekb: 1,
      fs: 0,
      iv_load_policy: 3,
      modestbranding: 1,
      playsinline: 1,
      rel: 0,
      cc_load_policy: 0,
    },
    events: {
      onReady: onPlayerReady,
      onStateChange: onPlayerStateChange,
      onError: onPlayerError,
    },
  });
}
