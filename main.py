from fastapi import FastAPI, WebSocket, Request, BackgroundTasks, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
import yt_dlp
import json
import os
import asyncio
from pathlib import Path

app = FastAPI()

# 存储当前活动的WebSocket连接
active_websocket = None

# 挂载静态文件和模板
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# 存储视频信息的JSON文件
VIDEOS_FILE = "videos.json"
# 视频下载目录
DOWNLOAD_DIR = "downloads"

# 确保必要的目录存在
Path(DOWNLOAD_DIR).mkdir(exist_ok=True)
if not os.path.exists(VIDEOS_FILE):
    with open(VIDEOS_FILE, "w", encoding='utf-8') as f:
        json.dump([], f)

# 读取已下载视频信息
def load_videos():
    with open(VIDEOS_FILE, "r", encoding='utf-8') as f:
        return json.load(f)

# 保存视频信息
def save_video_info(video_info):
    videos = load_videos()
    videos.append(video_info)
    with open(VIDEOS_FILE, "w", encoding='utf-8') as f:
        json.dump(videos, f, ensure_ascii=False)

# 主页路由
@app.get("/")
async def home(request: Request):
    videos = load_videos()
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "videos": videos}
    )

# WebSocket连接处理下载进度
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    global active_websocket
    await websocket.accept()
    active_websocket = websocket
    try:
        while True:
            await websocket.receive_text()
    except Exception:
        pass
    finally:
        active_websocket = None

# 下载进度回调
async def download_progress_hook(d, websocket):
    if d['status'] == 'downloading':
        try:
            progress = (d['downloaded_bytes'] / d['total_bytes']) * 100
            await websocket.send_json({
                'progress': progress,
                'speed': d.get('speed', 0),
                'eta': d.get('eta', 0)
            })
        except Exception:
            pass

# 下载视频
async def download_video(url: str):
    if not active_websocket:
        return
        
    ydl_opts = {
        'format': 'best',
        'outtmpl': os.path.join(DOWNLOAD_DIR, '%(title)s.%(ext)s'),
        'progress_hooks': [lambda d: asyncio.create_task(download_progress_hook(d, active_websocket))]
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            
            file_path = os.path.join(DOWNLOAD_DIR, f"{info['title']}.{info['ext']}")
            video_info = {
                'title': info['title'],
                'duration': info['duration'],
                'uploader': info['uploader'],
                'description': info['description'],
                'filepath': file_path.replace('\\', '/'),  # 统一使用正斜杠
                'filesize': os.path.getsize(file_path)
            }
            
            save_video_info(video_info)
            await active_websocket.send_json({'status': 'completed', 'video_info': video_info})
            
    except Exception as e:
        if active_websocket:
            await active_websocket.send_json({'status': 'error', 'message': str(e)})

# 开始下载路由
@app.post("/download")
async def start_download(request: Request, background_tasks: BackgroundTasks):
    form_data = await request.form()
    url = form_data.get('url')
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")
    background_tasks.add_task(download_video, url)
    return {"message": "Download started"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
