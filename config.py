class CompetitionConfig:
    VERSION = "0.0.1"
    NAME = 'Lab #'
    
    # UTC TIME (YYYY/MM/DD HH:MM:SS)
    OPEN_TIME = '2022/11/03 12:00:00'
    CLOSE_TIME = '2022/11/16 13:35:00'
    LIDER_PUBLIC = '2022/11/26 00:00:00'
    WINNER_INFO = '2022/11/30 00:00:00'
    TERMINATE_TIME = '2022/11/30 00:00:00'

    # USERS with special behaviours
    ADMIN_USER_ID = "prof"
    BASELINE_USER_ID = "baseline"

    UPLOAD_FOLDER = './uploads'  # Where to store submissions
    DUMP_FOLDER = './dumps'  # Where to store DB dumps with scores

    TEST_FILE_PATH = './static/test_solution/test_solution.csv'  # './static/test_solution/eval_solution.csv'
    MAX_FILE_SIZE = 32 * 1024 * 1024  # limit upload file size to 32MB
    API_FILE = 'mappings.dummy.json'  # API mappings
    DB_FILE = 'sqlite:///test.db'
    # TIME_BETWEEN_SUBMISSIONS = 60 * 60 * 4.8  # 5 minutes between submissions
    TIME_BETWEEN_SUBMISSIONS = 5
    MAX_NUMBER_SUBMISSIONS = 80
