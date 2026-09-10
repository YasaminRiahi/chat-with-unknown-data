# راهنمای Docker و FRP پروژه

این پروژه با معماری زیر اجرا می‌شود:

- `FastAPI` داخل کانتینر `api`
- فرانت‌اند و Nginx داخل کانتینر `web`
- Ollama مستقیماً روی سیستم میزبان (خارج از Docker)
- FRP Client روی سیستم میزبان
- پورت محلی پروژه: `127.0.0.1:25796`
- آدرس فعلی FRP: `171.22.26.98:25796`

## پیش‌نیازها

موارد زیر باید روی سیستم نصب و در حال اجرا باشند:

- Docker Desktop
- Ollama

مطمئن شوید Ollama اجرا شده و مدل `bge-m3` موجود است:

```powershell
ollama list
ollama pull bge-m3
```

فایل `.env` باید در ریشه پروژه وجود داشته باشد و حداقل `GROQ_API_KEY` معتبر در آن قرار گرفته باشد. فایل `.env` را در Git ثبت یا برای دیگران ارسال نکنید.

## رفتن به پوشه پروژه

دستورات را در PowerShell و از ریشه پروژه اجرا کنید:

```powershell
cd "E:\B Project\chat-with-unknown-data"
```

## اولین ساخت و اجرا

برای ساخت imageها و اجرای سرویس‌ها:

```powershell
docker compose up -d --build
```

پس از آماده‌شدن سرویس‌ها، پروژه از این آدرس در دسترس است:

```text
http://127.0.0.1:25796
```

## مشاهده وضعیت سرویس‌ها

```powershell
docker compose ps
```

سرویس `api` باید در وضعیت `healthy` و سرویس `web` در وضعیت `running` یا `Up` باشد.

## مشاهده لاگ‌ها

لاگ همه سرویس‌ها:

```powershell
docker compose logs -f
```

فقط لاگ FastAPI:

```powershell
docker compose logs -f api
```

فقط لاگ Nginx و فرانت‌اند:

```powershell
docker compose logs -f web
```

برای خروج از حالت نمایش زنده لاگ‌ها، کلیدهای `Ctrl+C` را فشار دهید. با این کار کانتینرها متوقف نمی‌شوند.

## توقف و اجرای مجدد

توقف و حذف کانتینرهای Compose، بدون حذف imageها و داده‌های دائمی:

```powershell
docker compose down
```

اجرای مجدد بدون build:

```powershell
docker compose up -d
```

راه‌اندازی مجدد سرویس‌های در حال اجرا:

```powershell
docker compose restart
```

## بعد از تغییر کد چه دستوری اجرا شود؟

### تغییر کد بک‌اند

اگر فایل‌های Python داخل `api` یا `pipeline` تغییر کردند، اجرا کنید:

```powershell
docker compose up -d --build
```

Docker فقط لایه مربوط به کد را دوباره می‌سازد و تا وقتی `requirements.txt` تغییر نکرده باشد، معمولاً وابستگی‌های Python دوباره دانلود نمی‌شوند.

### تغییر فرانت‌اند

پوشه `frontend` مستقیماً به کانتینر Nginx متصل است. بعد از تغییر فایل‌های آن معمولاً build لازم نیست؛ صفحه را با `Ctrl+F5` به‌صورت کامل refresh کنید.

در صورت نیاز می‌توان فقط سرویس وب را restart کرد:

```powershell
docker compose restart web
```

### تغییر وابستگی‌ها

بعد از تغییر `requirements.txt` اجرا کنید:

```powershell
docker compose up -d --build
```

در این حالت لایه نصب وابستگی‌ها دوباره اجرا می‌شود و بسته‌های جدید دانلود خواهند شد.

### تغییر Dockerfile یا Compose

بعد از تغییر `Dockerfile` یا `compose.yaml` نیز اجرا کنید:

```powershell
docker compose up -d --build
```

## نحوه کارکرد cache لایه‌های Docker

ترتیب کلی Dockerfile به این صورت است:

```text
نصب بسته‌های سیستم‌عامل       ← معمولاً از cache
کپی requirements.txt          ← معمولاً از cache
نصب وابستگی‌های Python        ← معمولاً از cache
کپی کد api و pipeline         ← بعد از تغییر کد دوباره ساخته می‌شود
```

به همین دلیل، تغییر معمولی کد باعث دانلود مجدد تمام dependencyها نمی‌شود.

دانلود یا ساخت مجدد dependencyها ممکن است در این شرایط اتفاق بیفتد:

- تغییر `requirements.txt`
- تغییر بخش‌های قبلی Dockerfile
- اجرای build با گزینه `--no-cache`
- پاک‌کردن Docker Build Cache
- حذف image پایه Python
- تغییر نسخه image پایه مانند `python:3.12-slim`

در حالت عادی از این دستور استفاده کنید:

```powershell
docker compose up -d --build
```

از دستور زیر فقط برای عیب‌یابی cache استفاده کنید، زیرا همه لایه‌ها را از ابتدا می‌سازد:

```powershell
docker compose build --no-cache
```

## داده‌های دائمی

cacheهای enrichment و embedding مستقیماً از پوشه `.cache` پروژه به `/app/.cache` داخل کانتینر متصل می‌شوند. در نتیجه cache فعلی پروژه استفاده می‌شود و با حذف یا ساخت مجدد کانتینر باقی می‌ماند. logهای مدل نیز در Docker Volume نگهداری می‌شوند. همه این داده‌ها با اجرای دستور زیر باقی می‌مانند:

```powershell
docker compose down
```

در حالت عادی از دستور زیر استفاده نکنید، زیرا Docker Volume مربوط به logها را حذف می‌کند. پوشه `.cache` پروژه با این دستور حذف نمی‌شود:

```powershell
docker compose down -v
```

## اتصال به Ollama روی سیستم میزبان

کانتینر FastAPI با آدرس زیر به Ollama روی ویندوز متصل می‌شود:

```text
http://host.docker.internal:11434
```

این مقدار در `compose.yaml` تنظیم شده است. پورت Ollama نباید از طریق FRP یا مستقیماً در اینترنت منتشر شود.

اگر API خطای اتصال به Ollama نشان داد:

1. مطمئن شوید Ollama در حال اجراست.
2. دستور `ollama list` را بررسی کنید.
3. مطمئن شوید مدل `bge-m3` دانلود شده است.
4. لاگ API را مشاهده کنید:

```powershell
docker compose logs -f api
```

## اتصال FRP

تنظیم فعلی موردنیاز در `frpc.ini`:

```ini
[ChatWithData]
type = tcp
local_ip = 127.0.0.1
local_port = 25796
remote_port = 25796
```

مسیر ترافیک به این شکل است:

```text
171.22.26.98:25796
        ↓ FRP
127.0.0.1:25796
        ↓ Docker/Nginx
FastAPI و frontend
```

ترتیب اجرای کامل:

1. Ollama را اجرا کنید.
2. کانتینرها را اجرا کنید:

   ```powershell
   docker compose up -d
   ```

3. آدرس محلی `http://127.0.0.1:25796` را تست کنید.
4. برنامه یا فایل start مربوط به `frpc` را اجرا کنید.
5. آدرس `http://171.22.26.98:25796` را از یک اینترنت یا دستگاه دیگر تست کنید.

خالی و باز بودن `remote_port` روی VPS فقط بعد از اتصال موفق FRP و تست از بیرون قطعی می‌شود.

## دستورات روزمره پیشنهادی

بعد از تغییر بک‌اند:

```powershell
docker compose up -d --build
docker compose logs -f api
```

برای اجرای عادی سیستم بدون تغییر کد:

```powershell
docker compose up -d
docker compose ps
```

برای خاموش‌کردن:

```powershell
docker compose down
```

## نکات اتصال دیتابیس

این برنامه دیتابیس داخلی ثابتی ندارد و فقط اتصال به Microsoft SQL Server را از داخل رابط کاربری می‌پذیرد.

اگر دیتابیس روی همان سیستم ویندوز اجرا می‌شود، در connection string داخل برنامه به‌جای `localhost` یا `127.0.0.1` از این hostname استفاده کنید:

```text
host.docker.internal
```

برای نمونه SQL Server روی سیستم میزبان:

```text
mssql+pyodbc://sa:password@host.docker.internal/database_name?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes
```

`localhost` از داخل کانتینر به خود کانتینر اشاره می‌کند، نه به سیستم ویندوز.
