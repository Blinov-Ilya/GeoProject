"""Обновление трёх таблиц Superset из CSV, экспортированных ноутбуком."""
import argparse
import csv
import os
from pathlib import Path
import subprocess
import tempfile

TABLES = {
    'object_signal': {
        'object_id': 'bigint', 'name': 'text', 'address': 'text',
        'operator': 'text', 'median_rsrp_dbm': 'double precision',
        'measurement_count': 'bigint', 'nearest_distance_m': 'double precision',
        'status': 'text', 'radius_m': 'bigint',
    },
    'rsrp_distribution': {
        'operator': 'text', 'rsrp_bin': 'bigint', 'measurement_count': 'bigint',
    },
    'daily_counts': {
        'survey_date': 'date', 'operator': 'text', 'measurement_count': 'bigint',
    },
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path,
                        default=Path(__file__).resolve().parents[1] / 'output')
    args = parser.parse_args()
    if not os.environ.get('DATABASE_URL'):
        parser.error('Задайте DATABASE_URL для PostgreSQL с данными отчёта.')
    statements = ['BEGIN;', 'CREATE SCHEMA IF NOT EXISTS vienna;']
    with tempfile.TemporaryDirectory(prefix='vienna-superset-') as temp:
        for table, columns in TABLES.items():
            source = args.data_dir / f'{table}.csv'
            normalized = Path(temp) / source.name
            with source.open(encoding='utf-8-sig', newline='') as src, normalized.open('w', encoding='utf-8', newline='') as dst:
                reader = csv.DictReader(src)
                missing = set(columns) - set(reader.fieldnames or [])
                if missing:
                    raise ValueError(f'{source.name}: нет столбцов {sorted(missing)}')
                writer = csv.DictWriter(dst, fieldnames=columns, extrasaction='ignore')
                writer.writeheader()
                count = 0
                for row in reader:
                    if None in row or any(row[column] is None for column in columns):
                        raise ValueError(f'{source.name}: неверное число полей в строке {reader.line_num}')
                    writer.writerow(row)
                    count += 1
                if not count:
                    raise ValueError(f'{source.name}: нет данных; прежние таблицы сохранены')
            csv_path = normalized.as_posix().replace("'", "''")
            fields = ', '.join(f'{name} {kind}' for name, kind in columns.items())
            statements.extend([
                f'CREATE TABLE IF NOT EXISTS vienna.{table} ({fields});',
                f'TRUNCATE TABLE vienna.{table};',
                f"\\copy vienna.{table} ({', '.join(columns)}) FROM '{csv_path}' WITH (FORMAT csv, HEADER true)",
            ])
        statements.append('COMMIT;')
        env = dict(os.environ, PGCLIENTENCODING='UTF8')
        result = subprocess.run(['psql', '-X', '--dbname', os.environ['DATABASE_URL'],
                                 '--set', 'ON_ERROR_STOP=1'],
                                input='\n'.join(statements) + '\n', text=True, encoding='utf-8', env=env)
        if result.returncode:
            raise SystemExit(result.returncode)
    print('Три таблицы обновлены. Обновите дашборд в Superset.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError) as error:
        raise SystemExit(str(error))
