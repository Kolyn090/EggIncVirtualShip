import {iconCatalog, iconImages} from './egginc-icons.mjs';

const targetAliases = {metronome: 'metronome', 'quantum-metronome': 'metronome',
  'tungsten-ankh': 'ankh', 'tau-ceti-geode': 'geode', 'gold-meteorite': 'meteorite',
  'mercurys-lens': 'lens', 'titanium-actuator': 'actuator', 'solar-titanium': 'titanium',
  'titanium-bar': 'titanium', 'titanium-ore': 'titanium'};
const shipAliases = {'chicken-heavy': 'heavy', 'corellihen-corvette': 'cornish',
  'millenium-chicken': 'quintillion-chicken', chickfiant: 'defihent', atreggies: 'henliner'};

export function missionIcon(kind, value) {
  if (typeof value !== 'string') return null;
  const family = value.trim().toLowerCase().replace(/-\d+$/, '');
  // Ship suffixes in actual optimizer data are duration types, not star levels.
  // The inspected source has one icon per ship family and no level variants.
  const entries = kind === 'ship' ? iconCatalog.ships : kind === 'target' ? iconCatalog.targets : {};
  const aliases = kind === 'ship' ? shipAliases : targetAliases;
  const name = Object.hasOwn(aliases, family) ? aliases[family] : family;
  return Object.hasOwn(entries, name) ? entries[name] : null;
}

export function planIcons(data) {
  const icons = {ships: Object.create(null), targets: Object.create(null), images: Object.create(null)};
  for (const row of data.schedule) {
    for (const [kind, key, collection] of [['ship', row.ship, icons.ships], ['target', row.target || 'none', icons.targets]]) {
      const icon = missionIcon(kind, key);
      collection[key] = icon;
      if (icon) icons.images[icon.file] = iconImages[icon.file];
    }
  }
  return icons;
}
