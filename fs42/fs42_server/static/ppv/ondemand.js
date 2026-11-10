// Pay-Per-View menu, in two tabs: Movies and Series. Up and down move through the
// list, left and right switch tabs. On a movie, SELECT opens its details (the full
// synopsis) and SELECT again plays it. On a series, SELECT opens it: Random Episode
// at the top, then its seasons; a season opens to its episodes, and SELECT on one
// plays it. Inside a series, left goes back up a level. The player comes back here
// when something ends (or on BACK), to the same place in the menu.
//
// Pressing right five times quickly on the Series tab shows the channel's hidden
// series folders too (a station's series_dirs entry with "hidden": true).
//
// Keys come from the remote through POST /ppv/{channel}/key/... as PageUp/PageDown/
// Enter/ArrowLeft/ArrowRight - real key presses are left alone, since the remote
// controller forwards those already.

const params = new URLSearchParams(location.search);
const CHANNEL = parseInt(params.get('channel'), 10);
const ROW_REM = 3.2;            // matches .list li height
const IDLE_BROWSE_MS = 90000;   // left alone this long, the menu starts browsing itself
const IDLE_STEP_MS = 12000;
const MUSIC_VOLUME = 0.3;
const SECRET_PRESSES = 5;       // right this many times...
const SECRET_WINDOW_MS = 2500;  // ...within this long

const SHELF_TAGS = { 'anime-movies': 'Anime' };

let movies = [];
let series = [];
let seriesLoaded = false;
let showHidden = false;
let rightPresses = [];

// where the menu is: the tab, and how deep into a series - each level keeps its own place
let tab = 'movies';
let stack = [];   // [{kind: 'series', data, index}, {kind: 'season', data, index}]
let tabIndex = { movies: 0, series: 0 };
let items = [];   // what the list shows now
let index = 0;

let lastKey = Date.now();
let ordering = false;
let synopsisOpen = false;
let busy = false;
let backdropFront = 'A';
let backdropTimer = null;

const $ = id => document.getElementById(id);

function rem() {
    return parseFloat(getComputedStyle(document.documentElement).fontSize);
}

async function applyLook() {
    // the same look as the guide - the seasonal one when seasonal themes are on
    try {
        const data = await (await fetch('/settings')).json();
        const look = data.guide_look || (data.values && data.values.guide_theme);
        if (look) document.body.dataset.look = look;
        // the DirecTV look shows the channel's number on its preview box
        document.body.dataset.channel = String(CHANNEL);
    } catch (e) {
        console.warn('Could not read the guide look:', e);
    }
}

// ---- what each kind of row shows ----

function movieItem(m) {
    return {
        kind: 'movie', title: m.nfo?.title || m.filename, sub: m.nfo?.info || '',
        tag: SHELF_TAGS[m.shelf] || '', overview: m.nfo?.description || '',
        poster: m.has_image ? m.image_url : null, backdrop: m.backdrop_url,
        action: 'Details', path: m.video_path, synopsis: true,
    };
}

function seriesItem(s) {
    return {
        kind: 'series', title: s.title, sub: s.year, tag: s.tag || '', overview: s.overview,
        poster: s.poster_url, backdrop: s.backdrop_url, action: 'Seasons', key: s.key, data: s,
    };
}

function seasonItems(detail) {
    const s = detail.series;
    const rows = [{
        kind: 'random', title: '▶ Random Episode', sub: `${detail.episode_count} eps`, tag: s.tag || '',
        overview: `Play any episode of ${s.title}, picked at random.`, poster: s.poster_url,
        backdrop: s.backdrop_url, action: 'Play random', key: s.key, heading: s.title,
    }];
    detail.seasons.forEach(season => rows.push({
        kind: 'season', title: season.label, sub: `${season.episodes.length} ep${season.episodes.length === 1 ? '' : 's'}`,
        tag: s.tag || '', overview: season.overview || s.overview, poster: season.poster_url || s.poster_url,
        backdrop: s.backdrop_url, action: 'Episodes', data: season, heading: s.title,
    }));
    return rows;
}

function episodeItems(season, s) {
    return season.episodes.map(e => ({
        kind: 'episode', title: e.number != null && !/^Episodes? /.test(e.title) ? `${e.number}. ${e.title}` : e.title,
        sub: '', tag: s.tag || '', overview: e.overview || '', poster: season.poster_url || s.poster_url,
        backdrop: e.still_url || s.backdrop_url, action: 'Play', path: e.path,
        heading: `${s.title} – ${season.label}`, playTitle: `${s.title}: ${e.title}`,
    }));
}

// ---- the list ----

function buildList() {
    const list = $('list');
    list.innerHTML = '';
    items.forEach(it => {
        const li = document.createElement('li');
        if (it.kind === 'random') li.classList.add('random-row');
        const title = document.createElement('span');
        title.className = 'row-title';
        title.textContent = it.title;
        const year = document.createElement('span');
        year.className = 'row-year';
        year.textContent = it.sub || '';
        li.append(title, year);
        list.append(li);
    });
}

function placeList() {
    // keep the highlighted row in the middle of the list window
    const windowEl = document.querySelector('.list-window');
    // a look can ask for a set number of whole rows sized to fill the list exactly
    const snap = parseInt(getComputedStyle(document.body).getPropertyValue('--list-snap'), 10);
    let rowPx = ROW_REM * rem();
    if (snap > 0) {
        rowPx = windowEl.clientHeight / snap;
        $('list').style.setProperty('--row-h', `${rowPx}px`);
    }
    let offset = windowEl.clientHeight / 2 - rowPx / 2 - index * rowPx;
    if (snap > 0) offset = Math.round(offset / rowPx) * rowPx;
    // the list always fills its box: near the top or bottom the highlight moves off
    // the middle instead of the list scrolling past its ends (a short list sits at the top)
    const lowest = Math.min(0, windowEl.clientHeight - items.length * rowPx);
    offset = Math.max(lowest, Math.min(0, offset));
    if (snap > 0 && lowest < 0) offset = Math.max(lowest, Math.round(offset / rowPx) * rowPx);
    $('list').style.transform = `translateY(${offset}px)`;
    [...$('list').children].forEach((li, i) => li.classList.toggle('selected', i === index));
    scrollLongTitle();
}

let titleScroll = null;

function scrollLongTitle() {
    // a highlighted title too long for its row slides across, holding at each end
    if (titleScroll) {
        titleScroll.animation.cancel();
        titleScroll.box.classList.remove('scrolling');
        titleScroll = null;
    }
    const box = $('list').children[index]?.querySelector('.row-title');
    if (!box) return;
    let inner = box.querySelector('.scroller');
    if (!inner) {
        inner = document.createElement('span');
        inner.className = 'scroller';
        inner.textContent = box.textContent;
        box.textContent = '';
        box.append(inner);
    }
    const distance = inner.scrollWidth - box.clientWidth;
    if (distance <= 2) return;
    box.classList.add('scrolling');
    const travel = distance / (6 * rem()) * 1000;   // about 6rem a second
    const hold = 1800;
    const total = travel + hold * 2;
    const animation = inner.animate([
        { transform: 'translateX(0)', offset: 0 },
        { transform: 'translateX(0)', offset: hold / total },
        { transform: `translateX(${-distance}px)`, offset: (hold + travel) / total },
        { transform: `translateX(${-distance}px)`, offset: 1 },
    ], { duration: total, iterations: Infinity });
    titleScroll = { animation, box };
}

function showBackdrop(url) {
    // fade between two layers; wait a moment so flicking through doesn't flash every one
    clearTimeout(backdropTimer);
    backdropTimer = setTimeout(() => {
        const back = backdropFront === 'A' ? 'B' : 'A';
        const front = $('backdrop' + backdropFront);
        const next = $('backdrop' + back);
        if (!url) {
            front.classList.remove('shown');
            return;
        }
        const img = new Image();
        img.onload = () => {
            next.style.backgroundImage = `url("${url}")`;
            next.classList.add('shown');
            front.classList.remove('shown');
            backdropFront = back;
        };
        img.src = url;
    }, 350);
}

// ---- the heading, tab label and hints for where the menu is ----

function updateChrome() {
    const top = stack[stack.length - 1];
    const heading = $('shelfHeading');
    heading.replaceChildren();
    if (!top) {
        // the tabs: Movies on the left, Series on the right
        const tabs = document.createElement('span');
        tabs.className = 'tabs';
        for (const [key, label] of [['movies', 'Movies'], ['series', 'Series']]) {
            const t = document.createElement('span');
            t.className = 'tab' + (key === tab ? ' active' : '');
            t.textContent = label;
            tabs.append(t);
        }
        heading.append(tabs);
    } else {
        const crumb = document.createElement('span');
        crumb.className = 'crumb';
        crumb.textContent = top.kind === 'series' ? top.data.series.title : `${stack[0].data.series.title} – ${top.data.label}`;
        heading.append(crumb);
    }
    const counter = document.createElement('span');
    counter.id = 'counter';
    counter.textContent = items.length ? `${index + 1} of ${items.length}` : '';
    heading.append(counter);

    // the panel's label (the DirecTV look shows it as a tab over the panel)
    $('main').dataset.label = !top ? (tab === 'movies' ? 'Movies' : 'Series')
        : top.kind === 'series' ? 'Seasons' : top.data.label;

    // the hints along the bottom
    const it = items[index];
    const hints = [['arrows', 'Browse']];
    if (!top) hints.push(['tabs', tab === 'movies' ? 'Series' : 'Movies']);
    else hints.push(['left', 'Back']);
    if (it) hints.push(['SELECT', it.action]);
    hints.push(['BACK', 'Exit during show']);
    setHints($('hints'), hints);
}

function keyBox(kind) {
    const k = document.createElement('span');
    k.className = 'key';
    if (kind === 'arrows') { k.classList.add('arrows'); k.innerHTML = '<i class="up"></i><i class="down"></i>'; }
    else if (kind === 'tabs') { k.classList.add('arrows', 'sideways'); k.innerHTML = '<i class="lt"></i><i class="rt"></i>'; }
    else if (kind === 'left') { k.classList.add('arrow-left'); k.innerHTML = '<i></i>'; }
    else if (kind === 'right') { k.classList.add('arrow-right'); k.innerHTML = '<i></i>'; }
    else k.textContent = kind;
    return k;
}

function setHints(box, hints) {
    box.replaceChildren(...hints.map(([kind, label]) => {
        const span = document.createElement('span');
        const text = document.createElement('span');
        text.className = 'hint-label';
        text.textContent = label;
        span.append(keyBox(kind), text);
        return span;
    }));
}

// ---- the selected row, shown big on the right ----

function showItem() {
    const it = items[index];
    placeList();
    updateChrome();
    if (!it) {
        $('title').textContent = tab === 'series' && !seriesLoaded ? 'Loading series…' : 'Nothing here yet';
        $('year').textContent = '';
        $('description').textContent = '';
        $('shelfTag').textContent = '';
        noPoster({ title: '' });
        return;
    }
    $('title').textContent = it.kind === 'episode' ? it.title.replace(/^\d+\. /, '') : it.title.replace(/^▶ /, '');
    $('year').textContent = it.kind === 'episode' ? stack[stack.length - 1].data.label : (it.sub || '');
    $('description').textContent = it.overview || '';
    $('shelfTag').textContent = it.tag || '';
    $('orderLabel').textContent = it.kind === 'movie' ? 'to see details'
        : it.kind === 'series' ? 'to see seasons' : it.kind === 'season' ? 'to see episodes'
        : it.kind === 'random' ? 'to play a random episode' : 'to watch now';

    const poster = $('poster');
    if (it.poster) {
        poster.classList.add('swapping');
        const img = new Image();
        img.onload = () => {
            if (items[index] !== it) return;
            poster.src = it.poster;
            poster.classList.remove('swapping');
            $('noPoster').classList.remove('shown');
        };
        img.onerror = () => noPoster(it);
        img.src = it.poster;
    } else {
        noPoster(it);
    }
    showBackdrop(it.backdrop);
}

function noPoster(it) {
    if (it.kind && items[index] !== it) return;
    $('poster').removeAttribute('src');
    $('noPoster').textContent = it.title || '';
    $('noPoster').classList.add('shown');
}

// ---- details (movies) ----

function openSynopsis() {
    const it = items[index];
    if (!it || ordering) return;
    $('synopsisTitle').textContent = it.title;
    $('synopsisYear').textContent = it.sub || '';
    $('synopsisTag').textContent = it.tag || '';
    $('synopsisBody').textContent = it.overview || 'No synopsis for this one.';
    if (it.poster) $('synopsisPoster').src = it.poster;
    else $('synopsisPoster').removeAttribute('src');
    $('synopsis').classList.add('shown');
    synopsisOpen = true;
}

function closeSynopsis() {
    $('synopsis').classList.remove('shown');
    synopsisOpen = false;
}

// ---- moving about ----

function setItems(newItems, newIndex = 0) {
    items = newItems;
    index = Math.max(0, Math.min(newIndex, items.length - 1));
    buildList();
    showItem();
}

function tabItems() {
    return tab === 'movies' ? movies.map(movieItem) : series.map(seriesItem);
}

function move(step) {
    if (!items.length || ordering) return;
    index = (index + step + items.length) % items.length;
    if (!stack.length) tabIndex[tab] = index;
    else stack[stack.length - 1].index = index;
    showItem();
}

function switchTab(to) {
    if (tab === to || stack.length) return;
    // going back to Movies locks the bonus series away again
    if (to === 'movies' && showHidden) {
        showHidden = false;
        rightPresses = [];
        seriesLoaded = false;
        series = [];
        tabIndex.series = 0;
    }
    if (to === 'movies') rightPresses = [];
    tab = to;
    setItems(tabItems(), tabIndex[tab]);
    if (tab === 'series' && !seriesLoaded) loadSeries();
}

function secretPress() {
    // right, five times quickly, on the Series tab: the hidden series join the list
    const now = Date.now();
    rightPresses = rightPresses.filter(t => now - t < SECRET_WINDOW_MS).concat(now);
    if (rightPresses.length >= SECRET_PRESSES && !showHidden && tab === 'series' && !stack.length) {
        rightPresses = [];
        showHidden = true;
        const keep = items[index] && items[index].key;
        loadSeries().then(() => {
            const i = items.findIndex(x => x.key === keep);
            if (i >= 0) { index = tabIndex.series = i; showItem(); }
            flash('Bonus series unlocked');
        });
    }
}

async function loadSeries() {
    try {
        const data = await (await fetch(`/ppv/${CHANNEL}/series${showHidden ? '?hidden=true' : ''}`)).json();
        series = data.series || [];
    } catch (e) {
        console.error('Could not load the series:', e);
        series = [];
    }
    seriesLoaded = true;
    if (tab === 'series' && !stack.length) setItems(tabItems(), tabIndex.series);
}

async function openSeries(it, restore) {
    busy = true;
    $('title').textContent = 'Loading…';
    try {
        const detail = await (await fetch(`/ppv/${CHANNEL}/series/detail?key=${encodeURIComponent(it.key)}`)).json();
        if (!detail.seasons) throw new Error('no seasons');
        stack = [{ kind: 'series', data: detail, index: restore ? restore.index : 0 }];
        setItems(seasonItems(detail), stack[0].index);
        if (restore && restore.season != null) {
            const season = detail.seasons.find(s => s.label === restore.season);
            if (season) openSeason(season, restore.episode);
        }
    } catch (e) {
        console.error('Could not open the series:', e);
        flash('Sorry - that series won\'t open right now');
        showItem();
    } finally {
        busy = false;
    }
}

function openSeason(season, at = 0) {
    stack.push({ kind: 'season', data: season, index: at });
    setItems(episodeItems(season, stack[0].data.series), at);
}

function back() {
    if (!stack.length) return;
    stack.pop();
    const top = stack[stack.length - 1];
    if (top) setItems(seasonItems(top.data), top.index);
    else setItems(tabItems(), tabIndex[tab]);
}

function select() {
    const it = items[index];
    if (!it || ordering || busy) return;
    if (synopsisOpen) return play(it.path, it.title);
    if (it.kind === 'movie') return openSynopsis();
    if (it.kind === 'series') return openSeries(it);
    if (it.kind === 'season') return openSeason(it.data);
    if (it.kind === 'episode') return play(it.path, it.playTitle || it.title);
    if (it.kind === 'random') return playRandom(it);
}

async function playRandom(it) {
    busy = true;
    try {
        const e = await (await fetch(`/ppv/${CHANNEL}/series/random?key=${encodeURIComponent(it.key)}`)).json();
        if (!e.path) throw new Error('none');
        busy = false;
        return play(e.path, `${it.heading}: ${e.title}`);
    } catch (err) {
        busy = false;
        flash('Sorry - no episodes found');
    }
}

function menuState() {
    const s = { tab, tabIndex: { ...tabIndex }, showHidden };
    if (stack.length) {
        s.series = stack[0].data.series.key;
        s.index = stack[0].index;
        if (stack[1]) { s.season = stack[1].data.label; s.episode = stack[1].index; }
    }
    return s;
}

async function play(path, title) {
    if (!path || ordering) return;
    ordering = true;
    closeSynopsis();
    $('startingTitle').textContent = title;
    $('starting').classList.add('shown');
    fadeMusic();
    try {
        // remember where the menu was, so it comes back here after
        await fetch(`/ppv/${CHANNEL}/menu_state`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ state: menuState() }),
        }).catch(() => {});
        const res = await fetch(`/ppv/${CHANNEL}/play_file`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ file_path: path }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        // the player closes this page and starts it
    } catch (e) {
        console.error('Could not start it:', e);
        $('startingTitle').textContent = 'Sorry - that one won\'t play right now';
        setTimeout(() => {
            $('starting').classList.remove('shown');
            ordering = false;
            startMusic();
        }, 3000);
    }
}

let flashTimer = null;
function flash(text) {
    const box = $('flash');
    box.textContent = text;
    box.classList.add('shown');
    clearTimeout(flashTimer);
    flashTimer = setTimeout(() => box.classList.remove('shown'), 2500);
}

document.addEventListener('keydown', e => {
    if (e.isTrusted) return;
    lastKey = Date.now();
    switch (e.key) {
        case 'PageUp':
        case 'ArrowUp':
            e.preventDefault();
            closeSynopsis();
            move(-1);
            break;
        case 'PageDown':
        case 'ArrowDown':
            e.preventDefault();
            closeSynopsis();
            move(1);
            break;
        case 'ArrowLeft':
            e.preventDefault();
            if (synopsisOpen) closeSynopsis();
            else if (stack.length) back();
            else switchTab('movies');
            break;
        case 'ArrowRight':
            e.preventDefault();
            if (synopsisOpen || stack.length) break;
            switchTab('series');
            secretPress();
            break;
        case 'Enter':
            e.preventDefault();
            select();
            break;
    }
});

function tickClock() {
    const now = new Date();
    let h = now.getHours();
    const ampm = h >= 12 ? 'PM' : 'AM';
    h = h % 12 || 12;
    $('clockTime').textContent = `${h}:${String(now.getMinutes()).padStart(2, '0')} ${ampm}`;
    $('clockDate').textContent = now.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' }).toUpperCase();
}

// ---- background music: the stock PPV playlist, quietly, until something starts ----
let tracks = [];
let track = 0;
let fadeTimer = null;

async function loadMusic() {
    try {
        const musicPath = params.get('music');
        if (musicPath) {
            const data = await (await fetch(`/media/list?path=${encodeURIComponent(musicPath)}&type=audio`)).json();
            tracks = data.files || [];
        } else {
            const data = await (await fetch('music_playlist.json')).json();
            tracks = data.music_files || [];
        }
    } catch (e) {
        tracks = [];
    }
    const audio = $('music');
    audio.addEventListener('ended', nextTrack);
    audio.addEventListener('error', () => tracks.length > 1 && nextTrack());
    if (tracks.length) {
        track = Math.floor(Math.random() * tracks.length);
        startMusic();
    }
}

function startMusic() {
    if (!tracks.length) return;
    const audio = $('music');
    clearInterval(fadeTimer);
    audio.volume = MUSIC_VOLUME;
    if (!audio.src) audio.src = tracks[track];
    audio.play().catch(() => {});
}

function nextTrack() {
    if (tracks.length > 1) {
        let next;
        do { next = Math.floor(Math.random() * tracks.length); } while (next === track);
        track = next;
    }
    $('music').src = tracks[track];
    $('music').play().catch(() => {});
}

function fadeMusic() {
    const audio = $('music');
    clearInterval(fadeTimer);
    fadeTimer = setInterval(() => {
        audio.volume = Math.max(0, audio.volume - 0.03);
        if (audio.volume <= 0) {
            clearInterval(fadeTimer);
            audio.pause();
        }
    }, 50);
}

// ---- picture-in-picture: the player parks the last channel in the preview box ----
function reportPip() {
    if (!navigator.userAgent.includes('FieldStation42-WebRender')) return;
    // the DirecTV look's preview box is its backdrop panel; the others have their own box
    const box = (document.body.dataset.look === 'directv' ? $('backdropA') : $('pip')).getBoundingClientRect();
    if (!box.width) return;
    const edge = parseFloat(getComputedStyle(document.body).getPropertyValue('--pip-border')) || 0;
    const px = innerHeight * edge / 100;
    const dpr = window.devicePixelRatio || 1;
    fetch('/player/guide/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            x: Math.round((window.screenX + box.left + px) * dpr),
            y: Math.round((window.screenY + box.top + px) * dpr),
            width: Math.round((box.width - 2 * px) * dpr),
            height: Math.round((box.height - 2 * px) * dpr),
        }),
    }).catch(() => {});
}

async function init() {
    tickClock();
    setInterval(tickClock, 1000);
    await applyLook();
    let saved = null;
    try {
        const [data, state] = await Promise.all([
            fetch(`/ppv/${CHANNEL}`).then(r => r.json()),
            fetch(`/ppv/${CHANNEL}/menu_state`).then(r => r.json()).catch(() => ({})),
        ]);
        movies = data.contents || [];
        saved = state && state.state;
    } catch (e) {
        $('loading').textContent = 'Could not load the menu';
        return;
    }
    if (params.has('tab')) saved = { tab: params.get('tab'), tabIndex: {} };

    // start somewhere different each time, like walking into the store - unless coming back
    tabIndex.movies = params.has('start') ? Math.min(parseInt(params.get('start'), 10) || 0, movies.length - 1)
                                          : Math.floor(Math.random() * Math.max(1, movies.length));
    if (saved) {
        tab = saved.tab === 'series' ? 'series' : 'movies';
        Object.assign(tabIndex, saved.tabIndex || {});
        showHidden = Boolean(saved.showHidden);
    }
    if (tab === 'series') await loadSeries();
    setItems(tabItems(), tabIndex[tab]);
    $('loading').classList.add('done');
    if (saved && saved.series) {
        const it = items.find(x => x.key === saved.series);
        if (it) await openSeries(it, saved);
    }
    if (tab === 'movies') loadSeries();

    window.addEventListener('fs42-aspect', e => {
        document.body.classList.toggle('aspect-4-3', e.detail && e.detail.ratio === '4:3');
        placeList();
    });
    window.addEventListener('resize', placeList);
    // the list's box can change size after the first layout (fonts loading, the
    // hints strip settling) - re-place it whenever it does
    new ResizeObserver(() => placeList()).observe(document.querySelector('.list-window'));
    // the channel that was on before keeps playing in the picture-in-picture box,
    // once the loading screen has gone
    setTimeout(reportPip, 600);
    window.addEventListener('resize', reportPip);
    window.addEventListener('fs42-aspect', () => setTimeout(reportPip, 100));

    // nobody at the remote for a while - browse the movies on its own, slowly
    setInterval(() => {
        if (!ordering && !synopsisOpen && !stack.length && tab === 'movies'
            && Date.now() - lastKey > IDLE_BROWSE_MS) move(1);
    }, IDLE_STEP_MS);
}

init();
