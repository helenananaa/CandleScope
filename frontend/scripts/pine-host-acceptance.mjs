import {fileURLToPath,pathToFileURL} from "node:url";
import path from "node:path";
import fs from "node:fs";
const root=fileURLToPath(new URL("../../",import.meta.url));
const stateIndex=process.argv.indexOf("--state");
if(stateIndex<0||!process.argv[stateIndex+1])throw new Error("Pass the isolated backend --state directory");
const out=path.resolve(process.argv[stateIndex+1]);
const {createServer}=await import(pathToFileURL(path.join(root,"frontend/node_modules/vite/dist/node/index.js")).href);
const backend=JSON.parse(fs.readFileSync(path.join(out,"backend.json"),"utf8"));
const server=await createServer({configFile:false,root:path.join(root,"frontend"),
  esbuild:{jsx:"automatic",jsxImportSource:"react"},resolve:{dedupe:["react","react-dom"]},
  server:{host:"127.0.0.1",port:0,fs:{allow:[root,fs.realpathSync(path.join(root,"frontend/node_modules"))]},
    proxy:{"/api":{target:`http://127.0.0.1:${backend.port}`,changeOrigin:true}}},
  plugins:[{name:"pine-host-acceptance-stop",configureServer(server){server.middlewares.use("/__acceptance_stop",(_request,response)=>{
    response.end("stopping");setTimeout(()=>void server.close(),100);
  });}}]});
await server.listen();
const port=server.httpServer.address().port;
const url=`http://127.0.0.1:${port}/tests/fixtures/pine-host-entry/entry.html`;
fs.writeFileSync(path.join(out,"browser.json"),JSON.stringify({url,pid:process.pid}));
console.log(url);
