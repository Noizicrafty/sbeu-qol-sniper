"""Frozen Windows entry point; no console window is required."""
import sys
import traceback
from itemsniper.paths import data_directory,bootstrap

if __name__=='__main__':
    directory=data_directory();directory.mkdir(parents=True,exist_ok=True)
    logs=directory/'logs';logs.mkdir(exist_ok=True)
    if sys.stdout is None:sys.stdout=open(logs/'stdout.log','a',encoding='utf8')
    if sys.stderr is None:sys.stderr=open(logs/'stderr.log','a',encoding='utf8')
    try:
        bootstrap(directory)
        if '--self-test' in sys.argv:
            from itemsniper.selftest import run
            run(directory)
        else:
            from itemsniper.app import main
            main()
    except Exception:
        (logs/'startup-error.log').write_text(traceback.format_exc(),encoding='utf8')
        raise
