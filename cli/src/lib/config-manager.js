import { existsSync, mkdirSync, readFileSync, writeFileSync, chmodSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';

const CONFIG_DIR = join(homedir(), '.devopsagent');
const CONFIG_FILE = join(CONFIG_DIR, 'config.json');

const DEFAULTS = {
  server_url: 'https://devopsagent.io',
};

function ensureDir() {
  if (!existsSync(CONFIG_DIR)) {
    mkdirSync(CONFIG_DIR, { recursive: true });
    try { chmodSync(CONFIG_DIR, 0o700); } catch { /* Windows may not support */ }
  }
}

export function loadConfig() {
  ensureDir();
  if (!existsSync(CONFIG_FILE)) {
    return { ...DEFAULTS };
  }
  try {
    const raw = readFileSync(CONFIG_FILE, 'utf-8');
    return { ...DEFAULTS, ...JSON.parse(raw) };
  } catch {
    return { ...DEFAULTS };
  }
}

export function saveConfig(config) {
  ensureDir();
  writeFileSync(CONFIG_FILE, JSON.stringify(config, null, 2) + '\n', 'utf-8');
  try { chmodSync(CONFIG_FILE, 0o600); } catch { /* Windows */ }
}

export function getApiKey() {
  const config = loadConfig();
  return config.api_key || null;
}

export function setApiKey(key) {
  const config = loadConfig();
  config.api_key = key;
  saveConfig(config);
}

export function removeApiKey() {
  const config = loadConfig();
  delete config.api_key;
  saveConfig(config);
}

export function getServerUrl() {
  const config = loadConfig();
  return config.server_url;
}

export function setConfigValue(key, value) {
  const config = loadConfig();
  config[key] = value;
  saveConfig(config);
}

export function getConfigPath() {
  return CONFIG_FILE;
}
