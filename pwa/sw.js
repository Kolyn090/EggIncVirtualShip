// App assets only. Plans and checklist progress are a single IndexedDB record;
// app-shell updates never replace, migrate, or delete that active plan.
const CACHE = 'egginc-mission-shell-6603e370fc9c0ec8';
const ASSETS = [
  "./",
  "./app.css",
  "./app.mjs",
  "./assets/egginc/ATTRIBUTION.md",
  "./assets/egginc/afx_aurelian_brooch_4.png",
  "./assets/egginc/afx_beak_of_midas_4.png",
  "./assets/egginc/afx_book_of_basan_4.png",
  "./assets/egginc/afx_carved_rainstick_4.png",
  "./assets/egginc/afx_clarity_stone_4.png",
  "./assets/egginc/afx_demeters_necklace_4.png",
  "./assets/egginc/afx_dilithium_monocle_4.png",
  "./assets/egginc/afx_dilithium_stone_4.png",
  "./assets/egginc/afx_gold_meteorite_3.png",
  "./assets/egginc/afx_interstellar_compass_4.png",
  "./assets/egginc/afx_life_stone_4.png",
  "./assets/egginc/afx_light_eggendil_4.png",
  "./assets/egginc/afx_lunar_stone_4.png",
  "./assets/egginc/afx_lunar_totem_4.png",
  "./assets/egginc/afx_mercurys_lens_4.png",
  "./assets/egginc/afx_neo_medallion_4.png",
  "./assets/egginc/afx_ornate_gusset_4.png",
  "./assets/egginc/afx_phoenix_feather_4.png",
  "./assets/egginc/afx_prophecy_stone_4.png",
  "./assets/egginc/afx_puzzle_cube_4.png",
  "./assets/egginc/afx_quantum_metronome_4.png",
  "./assets/egginc/afx_quantum_stone_4.png",
  "./assets/egginc/afx_shell_stone_4.png",
  "./assets/egginc/afx_ship_atreggies.png",
  "./assets/egginc/afx_ship_bcr.png",
  "./assets/egginc/afx_ship_chicken_1.png",
  "./assets/egginc/afx_ship_chicken_9.png",
  "./assets/egginc/afx_ship_chicken_heavy.png",
  "./assets/egginc/afx_ship_corellihen_corvette.png",
  "./assets/egginc/afx_ship_defihent.png",
  "./assets/egginc/afx_ship_galeggtica.png",
  "./assets/egginc/afx_ship_henerprise.png",
  "./assets/egginc/afx_ship_in_a_bottle_4.png",
  "./assets/egginc/afx_ship_millenium_chicken.png",
  "./assets/egginc/afx_ship_voyegger.png",
  "./assets/egginc/afx_solar_titanium_3.png",
  "./assets/egginc/afx_soul_stone_4.png",
  "./assets/egginc/afx_tachyon_deflector_4.png",
  "./assets/egginc/afx_tachyon_stone_4.png",
  "./assets/egginc/afx_tau_ceti_geode_3.png",
  "./assets/egginc/afx_terra_stone_4.png",
  "./assets/egginc/afx_the_chalice_4.png",
  "./assets/egginc/afx_titanium_actuator_4.png",
  "./assets/egginc/afx_tungsten_ankh_4.png",
  "./assets/egginc/afx_vial_martian_dust_4.png",
  "./assets/egginc/manifest.json",
  "./checklist.mjs",
  "./dashboard-template.mjs",
  "./egginc-icons.mjs",
  "./frame.mjs",
  "./icon.svg",
  "./icons.mjs",
  "./index.html",
  "./manifest.webmanifest",
  "./plan.mjs",
  "./store.mjs"
];
const urls = ASSETS.map(path => new URL(path, self.registration.scope).href);
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(urls.map(url => new Request(url, {cache: 'reload'}))))
    .then(() => self.skipWaiting()));
});
self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key.startsWith('egginc-mission-shell-') && key !== CACHE)
    .map(key => caches.delete(key)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET' || new URL(event.request.url).origin !== self.location.origin) return;
  if (event.request.mode === 'navigate') {
    event.respondWith(caches.open(CACHE).then(cache => cache.match(new URL('./index.html', self.registration.scope).href))
      .then(cached => cached || fetch(event.request)));
  } else if (urls.includes(event.request.url)) {
    event.respondWith(caches.open(CACHE).then(cache => cache.match(event.request)).then(cached => cached || fetch(event.request)));
  }
});
