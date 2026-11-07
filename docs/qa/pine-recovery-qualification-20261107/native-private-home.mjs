import fs from 'node:fs/promises';
import * as q from '../indicator-domain-native-20261106/native-driver.mjs';

const home = q.s.root + '/home';
await fs.mkdir(home);
q.s.env = { ...q.s.env, HOME: home, LOCALAPPDATA: home };
await import('./native-extended-probe.mjs');
