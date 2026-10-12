import {test} from 'node:test';
import assert from 'node:assert/strict';
import {groupReports,escapeHtml} from './src/data.js';
test('report chart aggregates unordered days and outcomes',()=>{
  assert.deepEqual(groupReports([{created_at:'2026-10-08T10:00:00Z',outcome:'blocked'},{created_at:'2026-10-07T10:00:00Z',outcome:'progress'},{created_at:'2026-10-08T11:00:00Z',outcome:'implemented'}]),[
    {day:'2026-10-07',total:1,progress:1,implemented:0,blocked:0,handoff:0},
    {day:'2026-10-08',total:2,progress:0,implemented:1,blocked:1,handoff:0}
  ]);
});
test('external text is escaped',()=>assert.equal(escapeHtml('<img src=x onerror="alert(1)">'), '&lt;img src=x onerror=&quot;alert(1)&quot;&gt;'));
