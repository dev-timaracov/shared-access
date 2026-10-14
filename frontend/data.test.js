import {test} from 'node:test';
import assert from 'node:assert/strict';
import {groupReports,escapeHtml,reportAuthor} from './src/data.js';
test('report chart aggregates unordered days and outcomes',()=>{
  assert.deepEqual(groupReports([{created_at:'2026-10-08T10:00:00Z',outcome:'blocked'},{created_at:'2026-10-07T10:00:00Z',outcome:'progress'},{created_at:'2026-10-08T11:00:00Z',outcome:'implemented'}]),[
    {day:'2026-10-07',total:1,progress:1,implemented:0,blocked:0,handoff:0},
    {day:'2026-10-08',total:2,progress:0,implemented:1,blocked:1,handoff:0}
  ]);
});
test('external text is escaped',()=>assert.equal(escapeHtml('<img src=x onerror="alert(1)">'), '&lt;img src=x onerror=&quot;alert(1)&quot;&gt;'));
test('report author displays saved name with ID and falls back for old reports',()=>{
  assert.equal(reportAuthor({developer_name:'Иван Иванов',developer_id:'admin'}),'Иван Иванов (admin)');
  assert.equal(reportAuthor({developer_name:null,developer_id:'admin'}),'admin');
  assert.equal(reportAuthor({developer_id:'alice'}),'alice');
  assert.equal(escapeHtml(reportAuthor({developer_name:'<b>Иван</b>',developer_id:'admin'})),'&lt;b&gt;Иван&lt;/b&gt; (admin)');
});
