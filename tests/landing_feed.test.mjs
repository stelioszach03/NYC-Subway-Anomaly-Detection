import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

for (const file of ['index.html', 'landing/index.html']) {
  const html = readFileSync(new URL(`../${file}`, import.meta.url), 'utf8');
  test(`${file}: an empty refresh clears previous anomalies`, async () => {
    const elements = new Map();
    const intervals = [];
    let rows = [{route_id:'A',stop_name:'Synthetic stop',anomaly_score:0.8,headway_sec:400,predicted_headway_sec:300}];
    const getElementById = id => {
      if (!elements.has(id)) elements.set(id,{innerHTML:'',textContent:'',querySelectorAll:()=>[]});
      return elements.get(id);
    };
    vm.runInNewContext(html.match(/<script>\s*([\s\S]*?)<\/script>/)[1], {
      document:{getElementById},setInterval:fn=>intervals.push(fn),
      fetch:async url=>({ok:true,json:async()=>url.includes('/anomalies')?rows:url.endsWith('/routes')?{routes:[]}:{} }),
    });
    await new Promise(resolve=>setImmediate(resolve));
    assert.match(getElementById('board-rows').innerHTML,/Synthetic stop/);
    rows = [];
    await intervals[1]();
    assert.doesNotMatch(getElementById('board-rows').innerHTML,/Synthetic stop/);
    assert.match(getElementById('board-rows').innerHTML,/no anomalies/i);
  });
  test(`${file}: initial markup does not fabricate incident rows`, () => {
    const board = html.split('id="board-rows"')[1].split('class="board-foot"')[0];
    assert.doesNotMatch(board,/board-score (critical|high|watch)/);
  });
}
