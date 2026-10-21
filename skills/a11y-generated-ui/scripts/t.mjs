import puppeteer from 'puppeteer-core';
const b=await puppeteer.launch({executablePath:'/usr/bin/chromium',headless:'new',args:["--disable-blink-features=WebTransport,WebTransportCustomCertificates"]});
const p=await b.newPage();await p.goto('http://localhost:18911/');
await p.evaluate("new WebTransport('https://127.0.0.1:54264/wt').ready.catch(()=>{})");await new Promise(r=>setTimeout(r,4000));await b.close();