FROM mcr.microsoft.com/playwright/python:v1.50.0-noble

# 設定時區為 Asia/Taipei
ENV TZ=Asia/Taipei
ENV PYTHONUNBUFFERED=1

RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# 安裝中文字體與系統依賴
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-noto-cjk \
    fonts-wqy-zenhei \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 安裝 Python 依賴
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 預裝 Playwright Chromium
RUN playwright install chromium

# 複製程式碼與設定檔
COPY config/ /app/config/
COPY src/ /app/src/
COPY scripts/ /app/scripts/

EXPOSE 8000

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
