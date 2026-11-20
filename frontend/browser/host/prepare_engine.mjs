// Prepare the staged Python tree with the Pyodide build that runs it in the
// browser, so the bytecode and computed metadata match it exactly.
//
// 1. Compute the pinned CCXT catalog (see catalog.py) into repo/ccxt_catalog.json.
// 2. Import the backend as the browser host configures it, in a fresh
//    interpreter, and record which staged modules that loads.
// 3. Compile those modules into __pycache__. Sources stay: several packages
//    read their own source (anyio's lazy importer uses inspect.getsource), and
//    modules imported later compile on first use as before.
// 4. Record the C extensions that import loaded, in order, in dynlibs.json.
//    The browser loads them before the interpreter starts, so that a memory
//    snapshot of the imported backend can be restored (see interpreter.mjs).
//
// The snapshot keeps whatever importing computed, so importing must not read
// or create anything in the data directory; the build fails if it does.
import { writeFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const runtime = resolve(here, '../node_modules/pyodide')
const stage = resolve(process.argv[2])
const { loadPyodide } = await import(pathToFileURL(resolve(runtime, 'pyodide.mjs')).href)
const started = Date.now()
const dataDir = '/tmp/candlescope-build'

async function interpreter() {
  const py = await loadPyodide({ indexURL: runtime + '/' })
  py.FS.mkdirTree('/stage')
  py.FS.mount(py.FS.filesystems.NODEFS, { root: stage }, '/stage')
  py.runPython(`
import glob, os, sys
sys.dont_write_bytecode = True
os.environ.update(CANDLE_DATA_DIR='${dataDir}', CANDLESCOPE_LOCAL_DATA_DIR='${dataDir}/local')
sys.path[:0] = ['/stage/packages', '/stage/repo', '/stage/repo/backend', *glob.glob('/stage/repo/packages/*/src')]
`)
  return py
}

const catalog = await interpreter()
await catalog.runPythonAsync(`
import json
from pathlib import Path
from app.exchanges.ccxt_ext.catalog import ccxt_catalog_document
document = ccxt_catalog_document()
Path('/stage/repo/ccxt_catalog.json').write_text(json.dumps(document, separators=(',', ':')), encoding='utf-8')
print(f"Computed the {len(document['entries'])}-exchange CCXT catalog")
`)

const host = await interpreter()
const dataAccess = new Set()
for (const operation of ['open', 'mkdir', 'rename', 'unlink', 'rmdir', 'symlink', 'truncate']) {
  const original = host.FS[operation]
  host.FS[operation] = function (path, ...rest) {
    if (typeof path === 'string' && (path === dataDir || path.startsWith(dataDir + '/'))) dataAccess.add(operation + ' ' + path)
    return original.call(this, path, ...rest)
  }
}
await host.runPythonAsync(`
import ast, importlib.util, os, py_compile, sys
from pathlib import Path

# The literal environment browser_host.py sets before importing the backend.
source = Path('/stage/repo/browser_host.py').read_text(encoding='utf-8')
for node in ast.walk(ast.parse(source)):
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'update'
            and isinstance(node.func.value, ast.Attribute) and node.func.value.attr == 'environ'):
        os.environ.update({k.arg: k.value.value for k in node.keywords if isinstance(k.value, ast.Constant)})
os.environ.update(CANDLE_DATA_DIR='${dataDir}', CANDLESCOPE_LOCAL_DATA_DIR='${dataDir}/local',
                  CANDLESCOPE_CCXT_CATALOG='/stage/repo/ccxt_catalog.json')
import browser_io, app.main, app.research_data.access, library_download  # noqa: F401

compiled = 0
for module in list(sys.modules.values()):
    path = getattr(module, '__file__', None) or ''
    if not path.startswith('/stage/') or not path.endswith('.py'):
        continue
    py_compile.compile(path, cfile=importlib.util.cache_from_source(path), dfile=path[len('/stage'):],
                       doraise=True, invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)
    compiled += 1
print(f'Compiled the {compiled} staged modules that starting the backend imports')
`)
if (dataAccess.size)
  throw Error('Importing the backend used the data directory, which a memory snapshot would keep: ' + [...dataAccess].join(', '))
const dynlibs = Object.keys(host._module.LDSO.loadedLibsByName).filter((name) => name !== '__main__')
if (dynlibs.some((name) => !name.startsWith('/stage/'))) throw Error('Unexpected C extension path: ' + dynlibs.join(', '))
writeFileSync(resolve(stage, 'dynlibs.json'), JSON.stringify({ dynlibs: dynlibs.map((name) => name.slice('/stage'.length)) }))
console.log(`Importing the backend loads ${dynlibs.length} C extensions`)
console.log(`Engine preparation took ${((Date.now() - started) / 1000).toFixed(1)} s`)
