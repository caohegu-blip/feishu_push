import uvicorn
import logging
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import os
from starlette.responses import FileResponse
from starlette.staticfiles import StaticFiles

# 导入项目内部模块
from app.api import main_router
from app.config import scheduler

# ===================== 全局日志配置 =====================
# 配置日志格式和级别
logging.basicConfig(
    level=logging.DEBUG,  # 调试级别，打印所有日志（生产环境可改为INFO）
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),  # 控制台输出
        logging.FileHandler("app.log", encoding="utf8")  # 保存到日志文件（项目根目录）
    ]
)
logger = logging.getLogger(__name__)


# ===================== 应用生命周期管理 =====================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI 生命周期管理（替代旧的 on_event）
    - 启动时：启动定时任务调度器
    - 关闭时：停止调度器
    """
    try:
        # 应用启动前执行
        logger.info("===== 飞书-Doris数据定时推送平台启动中 =====")

        # 启动定时任务调度器（确保只启动一次）
        if not scheduler.running:
            scheduler.start()
            logger.info("定时任务调度器启动成功")
        else:
            logger.info("定时任务调度器已在运行")

        yield  # 应用运行中

    except Exception as e:
        logger.error(f"应用启动失败：{str(e)}", exc_info=True)
        raise
    finally:
        # 应用关闭时执行
        logger.info("===== 飞书-Doris数据定时推送平台关闭中 =====")
        if scheduler.running:
            scheduler.shutdown()
            logger.info("定时任务调度器已停止")
        else:
            logger.info("定时任务调度器未运行，无需停止")


# ===================== 创建FastAPI应用实例 =====================
app = FastAPI(
    title="飞书-Doris数据定时推送平台",
    description="基于FastAPI + APScheduler实现的Doris数据定时推送至飞书机器人的服务",
    version="1.0.0",
    lifespan=lifespan  # 绑定生命周期函数
)

# ===================== 跨域配置（CORS） =====================
# 解决前端跨域请求问题
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 开发环境允许所有来源（生产环境需指定具体域名，如["http://localhost:8000"]）
    allow_origin_regex="http://.*|https://.*",  # 兼容所有http/https协议的域名
    allow_credentials=True,  # 允许携带Cookie等凭证
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],  # 允许的HTTP方法
    allow_headers=["*"],  # 允许所有请求头
    expose_headers=["*"],  # 暴露所有响应头
    max_age=3600  # 预检请求缓存时间（秒），减少OPTIONS请求次数
)


# ===================== 全局异常处理器 =====================
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    捕获所有未处理的异常，返回友好的错误信息并记录详细日志
    避免返回500 Internal Server Error时无任何错误详情
    """
    # 记录完整的异常堆栈（便于排查问题）
    logger.error(
        f"全局未捕获异常 | 请求URL: {request.url} | 方法: {request.method} | 错误: {str(exc)}",
        exc_info=True
    )

    # 返回结构化的错误响应
    return JSONResponse(
        status_code=500,
        content={
            "status": "failed",
            "error": "服务器内部错误",
            "detail": str(exc)[:500],  # 截断错误信息，避免返回过长内容
            "request_url": str(request.url),
            "request_method": request.method
        }
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """
    处理主动抛出的HTTPException（如参数错误、资源不存在等）
    """
    logger.warning(
        f"HTTP异常 | 请求URL: {request.url} | 状态码: {exc.status_code} | 详情: {exc.detail}"
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "status": "failed",
            "error": exc.detail,
            "request_url": str(request.url),
            "status_code": exc.status_code
        }
    )


# ===================== 注册路由 =====================
# 注册主路由（所有接口都在main_router中）
app.include_router(main_router)
app.mount("/static", StaticFiles(directory="static"), name="static")


# ===================== 3. 根路径路由（访问http://localhost:8000直接跳转到static/index.html） =====================
@app.get("/")
async def root():
    # 拼接static/index.html的绝对路径
    index_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
    # 校验文件是否存在
    if not os.path.exists(index_path):
        raise HTTPException(
            status_code=404,
            detail=f"前端页面不存在！路径：{index_path}\n请确认index.html放在static文件夹下"
        )
    return FileResponse(index_path)


# ===================== 健康检查接口 =====================
@app.get("/health", tags=["健康检查"])
async def health_check():
    """
    服务健康检查接口（可用于监控）
    """
    return {
        "status": "success",
        "service": "飞书-Doris数据定时推送平台",
        "version": "1.0.0",
        "scheduler_running": scheduler.running,
        "timestamp": logging.Formatter("%Y-%m-%d %H:%M:%S").format(logging.logTime())
    }


# ===================== 启动服务 =====================
if __name__ == "__main__":
    """
    启动FastAPI服务
    - 地址：0.0.0.0（允许外部访问）
    - 端口：8000
    - 热重载：reload=True（开发环境使用，生产环境关闭）
    """
    # 打印当前目录和文件路径（便于排查）
    print(f"项目根目录：{os.path.dirname(__file__)}")
    print(f"前端页面路径：{os.path.join(os.path.dirname(__file__), 'static', 'index.html')}")

    # 启动服务（绑定0.0.0.0:8000）
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=7000,
        reload=False,  # 开发模式自动重载
        log_level="debug"
    )