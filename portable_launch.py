from updater.launcher import main
from updater.portable import prepare_runtime, runtime_root

if __name__ == '__main__':
    raise SystemExit(main(root=runtime_root, prepare=prepare_runtime))
