import traceback

from flask import Flask, session, redirect, url_for
from flask import render_template, request
from flask_cors import CORS
import competition_tools
import os
import secrets
from api_utils import ApiAuth
from models import db, Submission, Evaluation
from competition_tools import eval_public_private, StageHandler
from sqlalchemy import func
from datetime import datetime

application = Flask(__name__, static_url_path="/app", static_folder="static")
application.config.from_object("config.CompetitionConfig")
application.secret_key = os.urandom(24)

CORS(application)

stage_handler = StageHandler(application.config['OPEN_TIME'],
                             application.config['CLOSE_TIME'],
                             application.config['TERMINATE_TIME'])

api_auth = ApiAuth(application.config['API_FILE'])
application.config["SQLALCHEMY_DATABASE_URI"] = application.config['DB_FILE']

db.init_app(application)
db.app = application
db.create_all()

competition_tools.check_solution_file(application.config['TEST_FILE_PATH'])

competition_tools.schedule_db_dump(application.config['CLOSE_TIME'], db, stage_name="CLOSE", dump_out=application.config['DUMP_FOLDER'])

competition_tools.schedule_db_dump(application.config['TERMINATE_TIME'], db, stage_name="TERMINATE", dump_out=application.config['DUMP_FOLDER'])

def get_user_id(api_key):
    if not api_auth.is_valid(api_key):
        # TODO build dictionary of possible errors & avoid hardcoding strings
        raise Exception("Недопустимый ключ API!")
    user_id = api_auth.get_user(api_key)
    return user_id

################
# Error Handling
################
@application.route('/error', methods=["GET"])
def error():
    error_message = request.args["error_message"]
    # return render_template('error_bad.html', error_message=str(error_message))
    return redirect(f'/?error_message={error_message}')

@application.errorhandler(413)
def request_entity_too_large(error):
    return redirect(url_for('error', error_message="Не удалось обработать запрос"))


@application.errorhandler(404)
def request_entity_too_large(error):
    return redirect(url_for('error', error_message="Страница, на которую вы хотели попасть, не доступна"))


################
# leaderboard
################
@application.route('/', methods=["GET"])
def leaderboard():
    try:

        lider_time = datetime.strptime(application.config["LIDER_PUBLIC"], "%Y/%m/%d %H:%M:%S")
        winner_time = datetime.strptime(application.config["WINNER_INFO"], "%Y/%m/%d %H:%M:%S")
        with_success = request.args.get("with_success")
        error_message = request.args.get("error_message")
        return render_template("firstPage.html",
                               open_time=stage_handler.open_time,
                               close_time=stage_handler.close_time,
                               lider_time=lider_time,
                               winner_time=winner_time,
                               is_ready=stage_handler.is_ready(),
                               is_terminate=stage_handler.is_terminated(),
                               with_success=with_success,
                               error_message=error_message)

    except Exception as ex:
        traceback.print_stack()
        traceback.print_exc()
        return redirect(url_for('error', error_message=ex))
        # return render_template("index.html")

if __name__ == '__main__':
    application.run(host='0.0.0.0', port=3030, debug=True)
