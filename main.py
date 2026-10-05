import os
import subprocess
import requests
import asyncio
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
import edge_tts
from gtts import gTTS

app = FastAPI()

class MergeRequest(BaseModel):
    video_urls: list[str]
    voice_text: str

OUTPUT_DIR = "/tmp/media_process"
os.makedirs(OUTPUT_DIR, exist_ok=True)

async def generate_voice(text: str, output_path: str):
    try:
        # تجربة Edge TTS بأعلى جودة
        communicate = edge_tts.Communicate(text=text, voice="ar-SA-HamedNeural")
        await communicate.save(output_path)
    except Exception as e:
        # بديل تلقائي فوري لو حصل حظر
        tts = gTTS(text=text, lang='ar')
        tts.save(output_path)

@app.post("/merge-video")
async def merge_video(req: MergeRequest):
    if not req.video_urls:
        raise HTTPException(status_code=400, detail="No video URLs provided")

    job_id = os.urandom(4).hex()
    audio_path = os.path.join(OUTPUT_DIR, f"voice_{job_id}.mp3")
    concat_list_path = os.path.join(OUTPUT_DIR, f"list_{job_id}.txt")
    final_output = os.path.join(OUTPUT_DIR, f"final_{job_id}.mp4")

    # 1. توليد التعليق الصوتي
    await generate_voice(req.voice_text, audio_path)

    # 2. تحميل كل الفيديوهات بالكامل
    video_files = []
    try:
        for idx, url in enumerate(req.video_urls):
            local_vid = os.path.join(OUTPUT_DIR, f"vid_{job_id}_{idx}.mp4")
            r = requests.get(url, stream=True, timeout=90)
            r.raise_for_status()
            with open(local_vid, 'wb') as f:
                for chunk in r.iter_content(chunk_size=1024*1024):
                    f.write(chunk)
            video_files.append(local_vid)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Video Download Error: {str(e)}")

    # 3. إعداد قائمة التتابع لـ FFmpeg
    with open(concat_list_path, "w", encoding="utf-8") as f:
        for v in video_files:
            f.write(f"file '{v}'\n")

    # 4. دمج كافة المشاهد مع الصوت حتى نهاية مدة الفيديوهات كاملة (18 ثانية)
    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", concat_list_path,
        "-i", audio_path,
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        final_output
    ]

    process = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if process.returncode != 0:
        err = process.stderr.decode('utf-8', errors='ignore')
        raise HTTPException(status_code=500, detail=f"FFmpeg error: {err}")

    # تنظيف المقاطع المؤقتة
    for v in video_files:
        if os.path.exists(v):
            try:
                os.remove(v)
            except:
                pass
    if os.path.exists(concat_list_path):
        try:
            os.remove(concat_list_path)
        except:
            pass

    return FileResponse(final_output, media_type="video/mp4", filename=f"video_{job_id}.mp4")
