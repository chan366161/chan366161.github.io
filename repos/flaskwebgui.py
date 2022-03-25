__version__ = "0.3.5"

import os
import sys
import time
from datetime import datetime
import logging
import tempfile
import socketserver
import subprocess as sps
from inspect import isfunction
from threading import Lock, Thread
from werkzeug.serving import make_server
from urllib.request import urlopen
import psutil as ps
import re
class ServerThread(Thread):
    def __init__(self,app,host,port):
        Thread.__init__(self)
        self._server = make_server(host,port,app)
        self._ctx = app.app_context()
        self._ctx.push()
    def start(self):
        self._server.serve_forever()
    def shutdown(self):
        self._server.shutdown()
logging.basicConfig(level=logging.INFO, format='flaskwebgui - [%(levelname)s] - %(message)s')

# UTILS

def find_chrome_mac():

    chrome_names = ['Google Chrome', 'Chromium']

    for chrome_name in chrome_names:
        default_dir = r'/Applications/{}.app/Contents/MacOS/{}'.format(chrome_name, chrome_name)
        if os.path.exists(default_dir):
            return default_dir

        # use mdfind ci to locate Chrome in alternate locations and return the first one
        name = '{}.app'.format(chrome_name)
        alternate_dirs = [x for x in sps.check_output(["mdfind", name]).decode().split('\n') if x.endswith(name)] 
        if len(alternate_dirs):
            return alternate_dirs[0] + '/Contents/MacOS/{}'.format(chrome_name)

    return None


def find_chrome_linux():
    try:
        import whichcraft as wch
    except Exception as e:
        raise Exception("whichcraft module is not installed/found  \
                            please fill browser_path parameter or install whichcraft!") from e

    chrome_names = ['chromium-browser',
                    'chromium',
                    'google-chrome',
                    'google-chrome-stable']

    for name in chrome_names:
        chrome = wch.which(name)
        if chrome is not None:
            return chrome
    return None



def find_chrome_win():

    #using edge by default since it's build on chromium
    edge_path = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    if os.path.exists(edge_path):
        return edge_path

    import winreg as reg
    reg_path = r'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe'

    chrome_path = None
    last_exception = None

    for install_type in reg.HKEY_CURRENT_USER, reg.HKEY_LOCAL_MACHINE:
        try:
            reg_key = reg.OpenKey(install_type, reg_path, 0, reg.KEY_READ)
            chrome_path = reg.QueryValue(reg_key, None)
            reg_key.Close()
        except WindowsError as e:
            last_exception = e
        else:
            if chrome_path and len(chrome_path) > 0:
                break

    # Only log some debug info if we failed completely to find chrome
    if not chrome_path:
        logging.exception(last_exception)
        logging.error("Failed to detect chrome location from registry")
    else:
        logging.info(f"Chrome path detected as: {chrome_path}")

    return chrome_path


def get_default_chrome_path():
    """
        Credits for get_instance_path, find_chrome_mac, find_chrome_linux, find_chrome_win funcs
        got from: https://github.com/ChrisKnott/Eel/blob/master/eel/chrome.py
    """
    if sys.platform in ['win32', 'win64']:
        return find_chrome_win()
    elif sys.platform in ['darwin']:
        return find_chrome_mac()
    elif sys.platform.startswith('linux'):
        return find_chrome_linux()




# class FlaskwebguiDjangoMiddleware:
      #TODO help needed here
#     def __init__(self, get_response=None):
#         self.get_response = get_response

#     def __call__(self, request):
#         response = self.get_response(request)
#         return response


current_timestamp = None
server_exit_req = False
browser_DOM_ready = False
class FlaskUI:
    
    def __init__(self, 
        app, 
        start_server='flask',
        host='127.0.0.1',
        port=None,
        width=800, 
        height=600, 
        maximized=False, 
        fullscreen=False, 
        browser_path=None, 
        socketio=None,
        on_exit=None,
        idle_interval=5,
        close_server_on_exit=True,
        hostfile=None
        ) -> None:

        self.app = app
        self.start_server = str(start_server).lower()
        self.host = host
        self.port = port
        self.width = str(width)
        self.height= str(height)
        self.fullscreen = fullscreen
        self.maximized = maximized
        self.browser_path = browser_path if browser_path else get_default_chrome_path()  
        self.socketio = socketio
        self.on_exit = on_exit
        self.idle_interval = idle_interval
        self.close_server_on_exit = close_server_on_exit
        self.hostfile = hostfile

        self.set_url()
        self._server = None
        self._client = None
        self._probe_lock = Lock()
        self.webserver_dispacher = {
            "flask": self.start_flask,
            "flask-socketio": self.start_flask_socketio,
            "django": self.start_django,
            "fastapi": self.start_fastapi
        }

        self.supported_frameworks = list(self.webserver_dispacher.keys())
    
        if self.close_server_on_exit: 
            self.lock = Lock()


    def update_timestamp(self):
        self.lock.acquire()
        global current_timestamp
        current_timestamp = datetime.now()
        self.lock.release()
        


    def run(self):
        """ 
        Starts 3 threads one for webframework server and one for browser gui 
        """

        if self.close_server_on_exit:
            self.update_timestamp()
        if self.hostfile is None:
            t_start_webserver = Thread(target=self.start_webserver)
            t_open_chromium   = Thread(target=self.open_chromium)
            t_stop_webserver  = Thread(target=self.stop_webserver)
            threads = [t_start_webserver, t_open_chromium, t_stop_webserver]

            for t in threads: t.start()
            for t in threads: t.join()
        else:
            t_open_chromium = Thread(target=self.open_chromium)
            threads = [t_open_chromium]
            for t in threads: t.start()
            for t in threads: t.join()


    def set_url(self):
        
        if self.port is None and self.hostfile is None:
            with socketserver.TCPServer(("localhost", 0), None) as s:
                free_port = s.server_address[1]
            self.port = free_port
        if self.hostfile is None:
            self.localhost = f"http://{self.host}:{self.port}"
        else:
            self.localhost = f"file://{self.hostfile}"
       

    def start_webserver(self):

        if isfunction(self.start_server):
            self.start_server()

        if self.start_server not in self.supported_frameworks:
            raise Exception(f"'start_server'({self.start_server}) not in {','.join(self.supported_frameworks)} and also not a function which starts the webframework")

        self.webserver_dispacher[self.start_server]()


    def add_flask_middleware(self):

        @self.app.after_request
        def keep_alive_after_request(response):
            self.keep_server_running()
            return response
        
        @self.app.route("/flaskwebgui-keep-server-alive")
        def keep_alive_pooling():
            self.keep_server_running()
            return "ok"

        @self.app.route("/exit")
        def deferred_server_exit():
            self.lock.acquire()
            global server_exit_req
            server_exit_req = True
            self.lock.release()
            return "ok"

        @self.app.route("/ready")
        def client_sign_in():
            self._probe_lock.acquire()
            global browser_DOM_ready
            browser_DOM_ready = True
            self._probe_lock.release()
            return "ok"

    def start_flask(self):
        
        if self.close_server_on_exit:
            self.add_flask_middleware()

        self._server = ServerThread(self.app, self.host, self.port)
        self.app.logger.info("Werkzeug start : "+ self.localhost)
        self._server.start()


    def start_flask_socketio(self):
        
        if self.close_server_on_exit:
            self.add_flask_middleware()
            
        self.socketio.run(self.app, host=self.host, port=self.port, debug=False)


    def start_django(self):
        try:
            import waitress
            waitress.serve(self.app, host=self.host, port=self.port)
        except:
            try:#linux and mac
                os.system(f"python3 manage.py runserver {self.port}")
            except:#windows
                os.system(f"python manage.py runserver {self.port}")
        

    def add_fastapi_middleware(self):
        
        @self.app.middleware("http")
        async def keep_alive_after_request(request, call_next):
            response = await call_next(request)
            self.keep_server_running()
            return response
        
        @self.app.route("/flaskwebgui-keep-server-alive")
        async def keep_alive_pooling():
            self.keep_server_running()
            return "ok"
        

    def start_fastapi(self):
        
        import uvicorn
    
        if self.close_server_on_exit:
            self.add_fastapi_middleware()
        
        uvicorn.run(self.app, host=self.host, port=self.port, log_level="warning")



    def open_chromium(self):
        """
            Open the browser selected (by default it looks for chrome)
            # https://peter.sh/experiments/chromium-command-line-switches/
        """
        logging.info(f"Opening browser at {self.localhost}")
        temp_profile_dir = os.path.join(tempfile.gettempdir(), "flaskwebgui")
        check_url = self.localhost + '/flaskwebgui-keep-server-alive'
        time_up = 30
        while time_up>0 and self.hostfile is None:
            check_rsp = urlopen(check_url, timeout=2)
            if check_rsp and check_rsp.read() == b'ok':
                break
            else:
                time.sleep(2)
                time_up -= 1

        if time_up>0 and self.browser_path:
            launch_options = None
            if self.fullscreen:
                launch_options = ["--start-fullscreen"]
            elif self.maximized:
                launch_options = ["--start-maximized"]
            else:
                launch_options = [f"--window-size={self.width},{self.height}"]
            #render_id = self._get_chrome_render_id()
            options = [
                self.browser_path, 
                #f"--user-data-dir={temp_profile_dir}",
                "--new-window", 
                "--no-first-run",
                "--disable-extensions",
                # "--window-position=0,0"
                ] + launch_options + [f'--app={self.localhost}']
            cmdline = '"'+ self.browser_path+'" '+ ' '.join(options[1:])
            self.app.logger.info(cmdline)
            browser_p = sps.Popen(options, stdout=sps.PIPE, stderr=sps.PIPE, stdin=sps.PIPE, shell=False)
            p=ps.Process(browser_p.pid)

            if not self._client and self.hostfile is None :
                self.app.logger.info("lookup process deferred")
                wait_browser = 30
                while wait_browser>0:
                    self._probe_lock.acquire()
                    global browser_DOM_ready
                    isclientgrownup = browser_DOM_ready
                    self._probe_lock.release()
                    if isclientgrownup:
                        self._client = True
                        break
                    else:
                        wait_browser -=1
                        time.sleep(2)
            elif not self._client and self.hostfile and browser_p :
                self._client = True

        elif time_up>0 :
            import webbrowser
            self._client = webbrowser.open_new(self.localhost)
        if self._client:
            self.app.logger.info("Browser grownup")
        else:
            self.app.logger.info("wait for Browser timeout")

    def _get_var(self,proc,var):
        try :
            return proc.environ().get(var,'N/A')
        except ps.AccessDenied as e:
            return str(e)


    def _get_chrome_render_id(self):
        temp_dir = tempfile.gettempdir()
        pids = ps.pids()
        time_ticks = 0
        render_id = ""
        for pid in pids:
            try:
                p = ps.Process(pid)
                if "chrome" in p.name() and '--type=renderer' in p.cmdline():
                    for each in p.open_files():
                        if temp_dir in each.path:
                            ctime = os.path.getctime(each.path)
                            if ctime > time_ticks:
                                time_ticks = ctime
                                for opt in p.cmdline():
                                    if opt.startswith("--renderer-client-id"):
                                        render_id = opt.split("=")[1]
                                        break
                            break
            except ps.NoSuchProcess as e:
                pass
        return render_id
    def _get_true_chrome_render_proc(self):
        pids = ps.pids()
        render_pid = 0
        time_tick = 0
        for pid in pids:
            try:
                p = ps.Process(pid)
                if "chrome" in p.name() and f'--type=renderer' in p.cmdline():
                    if p.create_time()>time_tick:
                        render_pid = pid
                        time_tick = p.create_time()

            except ps.NoSuchProcess as e:
                pass
        if render_pid != 0:
            return ps.Process(render_pid)
        else:
            return None
    def _get_chrome_render_proc(self):
        temp_dir = tempfile.gettempdir()
        pids = ps.pids()
        time_ticks = 0
        render_pid = 0
        for pid in pids:
            try:
                p = ps.Process(pid)
                if "chrome" in p.name() and  '--type=renderer' in p.cmdline():
                    for each in p.open_files():
                        if temp_dir in each.path:
                            ctime = os.path.getctime(each.path)
                            if ctime > time_ticks:
                                time_ticks = ctime
                                render_pid = pid
                            break
            except ps.NoSuchProcess as e:
                pass
        if render_pid != 0:
            return ps.Process(render_pid)
        else:
            return None
    def _proc_status(self,proc):
        proc_s = str(proc)
        match = re.search(r"""status=['"](.*)['"],""", proc_s)
        return match.group(1)

    def stop_webserver(self):
        
        if self.close_server_on_exit is False: return
        
        #TODO add middleware for Django
        if self.start_server == 'django':
            logging.info("Middleware not implemented (yet) for Django.")
            return
        max_retry = 2
        wait_server = 12
        while max_retry>0 and wait_server>0:
            self.lock.acquire()
            global current_timestamp
            delta_seconds = (datetime.now() - current_timestamp).total_seconds()
            global server_exit_req
            server_exit_flag = server_exit_req
            self.lock.release()
            #if delta_seconds > 2 * self.idle_interval:
            #    logging.info("App closed")
            #    break
            if server_exit_flag:
                logging.info("App closed")
                self.app.logger.info("App closed")
                self.app.logger.info("Browser closed")
                break
            if not self._server:
                wait_server -= 1

            else:
                if not self._client :
                    max_retry -= 1
                    if max_retry==0:
                        self.app.logger.info("Browser abnormal")

            time.sleep(self.idle_interval)

        if self._server:
            self._server.shutdown()
            
        if isfunction(self.on_exit): 
            logging.info(f"Executing {self.on_exit.__name__} function...")
            try:
                self.on_exit()
            except Exception as e:
                self.app.logger.warning(str(e))

        logging.info("Closing connections...")
        self.app.logger.info("Shutdown server")
        #os.kill(os.getpid(), 9)


    def keep_server_running(self):
        self.update_timestamp()
        return "Ok"

        
