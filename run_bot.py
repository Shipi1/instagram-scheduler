from app.runner import main


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(f'Error de arranque/servicio: {error}', flush=True)
        raise SystemExit(1)
