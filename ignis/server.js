const express = require('express');
const fs = require('fs');
const path = require('path');
const { WebSocketServer } = require('ws');
const http = require('http');
const archiver = require('archiver');

const app = express();
app.use(express.json({ limit: '50mb' }));

const VAULTS_DIR = process.env.VAULTS_DIR || '/data/vaults';
const PORT = process.env.IGNIS_PORT || 8080;

fs.mkdirSync(VAULTS_DIR, { recursive: true });

function countNotes(dir) {
    let count = 0;
    try {
        const items = fs.readdirSync(dir);
        for (const item of items) {
            const full = path.join(dir, item);
            const stat = fs.statSync(full);
            if (stat.isDirectory()) count += countNotes(full);
            else if (item.endsWith('.md')) count++;
        }
    } catch {}
    return count;
}

function getTree(dir, prefix = '') {
    const entries = [];
    try {
        const items = fs.readdirSync(dir);
        for (const item of items) {
            const full = path.join(dir, item);
            const stat = fs.statSync(full);
            const rel = prefix ? `${prefix}/${item}` : item;
            if (stat.isDirectory()) {
                entries.push({ name: item, type: 'directory', path: rel, children: getTree(full, rel) });
            } else {
                entries.push({ name: item, type: 'file', path: rel, size: stat.size });
            }
        }
    } catch {}
    return entries;
}

// Health
app.get('/obsidian/health', (req, res) => res.json({ status: 'ok', service: 'ignis', vaults_dir: VAULTS_DIR }));

// UI placeholder
app.get('/obsidian', (req, res) => {
    res.send('<html><head><title>Ignis Obsidian</title></head><body><h1>Ignis Obsidian Server</h1><p>API: /api/vaults</p></body></html>');
});

app.get('/vault', (req, res) => res.redirect('/obsidian'));

// List vaults
app.get('/api/vaults', (req, res) => {
    const vaults = fs.readdirSync(VAULTS_DIR).filter(f => {
        try { return fs.statSync(path.join(VAULTS_DIR, f)).isDirectory(); }
        catch { return false; }
    }).map(name => ({
        name,
        path: `/data/vaults/${name}`,
        noteCount: countNotes(path.join(VAULTS_DIR, name)),
    }));
    res.json(vaults);
});

// Create vault
app.post('/api/vaults/create', (req, res) => {
    const { name } = req.body;
    if (!name) return res.status(400).json({ error: 'name required' });
    const vaultPath = path.join(VAULTS_DIR, name);
    fs.mkdirSync(vaultPath, { recursive: true });
    fs.mkdirSync(path.join(vaultPath, 'Daily Notes'), { recursive: true });
    fs.mkdirSync(path.join(vaultPath, 'Memories'), { recursive: true });
    res.json({ name, path: vaultPath });
});

// Bootstrap vault
app.get('/api/bootstrap/:vault', (req, res) => {
    const vaultPath = path.join(VAULTS_DIR, req.params.vault);
    if (!fs.existsSync(vaultPath)) return res.status(404).json({ error: 'Vault not found' });
    res.json({
        vault: req.params.vault,
        tree: getTree(vaultPath),
        plugins: [],
        metadata: {},
    });
});

// Read file
app.get('/api/files/:vault/*', (req, res) => {
    const filePath = path.join(VAULTS_DIR, req.params.vault, req.params[0]);
    try {
        const content = fs.readFileSync(filePath, 'utf-8');
        res.json({ path: req.params[0], content });
    } catch { res.status(404).json({ error: 'Not found' }); }
});

// Write file
app.post('/api/files/:vault/*', (req, res) => {
    const filePath = path.join(VAULTS_DIR, req.params.vault, req.params[0]);
    const { content } = req.body;
    if (content === undefined) return res.status(400).json({ error: 'content required' });
    fs.mkdirSync(path.dirname(filePath), { recursive: true });
    fs.writeFileSync(filePath, content, 'utf-8');
    broadcast({ type: 'file_update', vault: req.params.vault, path: req.params[0], content });
    res.json({ status: 'ok', path: req.params[0] });
});

// Delete file
app.delete('/api/files/:vault/*', (req, res) => {
    const filePath = path.join(VAULTS_DIR, req.params.vault, req.params[0]);
    try { fs.unlinkSync(filePath); res.json({ status: 'deleted' }); }
    catch { res.status(404).json({ error: 'Not found' }); }
});

// Download vault as zip
app.get('/api/vaults/:vault/zip', (req, res) => {
    const vaultPath = path.join(VAULTS_DIR, req.params.vault);
    if (!fs.existsSync(vaultPath)) return res.status(404).json({ error: 'Vault not found' });
    res.setHeader('Content-Type', 'application/zip');
    res.setHeader('Content-Disposition', `attachment; filename="${req.params.vault}.zip"`);
    const archive = archiver('zip', { zlib: { level: 9 } });
    archive.pipe(res);
    archive.directory(vaultPath, req.params.vault);
    archive.finalize();
});

// HTTP server + WebSocket
const server = http.createServer(app);
const wss = new WebSocketServer({ server });

const clients = new Set();

wss.on('connection', (ws) => {
    clients.add(ws);
    ws.on('close', () => clients.delete(ws));
    ws.on('error', () => clients.delete(ws));
});

function broadcast(data) {
    const msg = JSON.stringify(data);
    for (const client of clients) {
        if (client.readyState === 1) client.send(msg);
    }
}

server.listen(PORT, '127.0.0.1', () => {
    console.log(`[Ignis] Obsidian server on http://127.0.0.1:${PORT}`);
});
