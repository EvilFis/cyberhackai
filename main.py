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
# submissions
################
@application.route('/entry', methods=["GET", "POST"])
def submissions(with_success=False):
    # TODO allow to admins the access

    if stage_handler.is_ready() or stage_handler.is_terminated():
        return redirect('https://cyberhackai.ru/')

    # Get API key from submissions form and show submissions
    api_key = request.form.get("APIKey", None)

    if api_key is None:
        print("Hello2")
        submissions_request_id = secrets.token_hex()
        session["submissions_request_id"] = submissions_request_id
        return render_template("entry.html",
                               submissions_request_id=submissions_request_id,
                               close_time=stage_handler.close_time,
                               is_closed=stage_handler.is_closed())
    else:
        try:
            if ("submissions_request_id" not in session.keys()) or \
                    (session["submissions_request_id"] != request.form.get('submissionsRequestId', None)):

                error_message = "Неправильный запрос. Используйте веб-страницу формы для загрузки решения или попробуйте перезагрузить страницу!"
                raise Exception(error_message)
            if not api_auth.is_valid(api_key):
                raise Exception("Недопустимый ключ API")

            session["api_key"] = api_key
            user_id = api_auth.get_user(api_key)

            application.logger.info(f"Получен запрос на проверку страницы отправки по идентификатору пользователя '{user_id}'.")

            Submission.query.filter_by(user_id=user_id).all()

            user_submissions = db.session \
                .query(Submission.id,
                       Submission.user_id,
                       Submission.timestamp,
                       Evaluation.evaluation_public,
                       Evaluation.private_check) \
                .join(Submission) \
                .filter_by(user_id=user_id) \
                .all()

            user_submissions = [(s_id, timestamp, user_id, competition_tools.score_mapper(score), check)
                                for s_id, timestamp, user_id, score, check in user_submissions]

            submissions_left = int(
                application.config['MAX_NUMBER_SUBMISSIONS'] - competition_tools.get_user_submissions_number(user_id=user_id,
                                                                                                     db=db))

            return render_template("myLab.html",
                                   submissions_request_id=session["submissions_request_id"],
                                   user_id=user_id,
                                   user_submissions=user_submissions,
                                   close_time=stage_handler.close_time,
                                   is_closed=stage_handler.is_closed(),
                                   left=submissions_left)

        except Exception as ex:
            traceback.print_stack()
            traceback.print_exc()
            return redirect(url_for('error', error_message=ex))

################
# leaderboard
################

@application.route('/', methods=["GET"])
def leaderboard():
    try:
        # To allow access to admins even is competition is ready or over
        user_id = None
        api_key = request.args.get("api_key", None)

        if api_key is not None:
            user_id = get_user_id(api_key)

        if ((user_id is None) or (user_id not in [application.config['ADMIN_USER_ID']])) and \
                stage_handler.is_ready():

            return redirect('https://cyberhackai.ru')

        else: # Get the leaderboard
            # TODO: here, we assume that a higher score is preferable.
            # it might not always be like this (e.g. MSE)
            # For those cases, func.min should be used: make this parameter
            # configurable from config file
            participants = db.session \
                .query(Submission.user_id, func.max(Evaluation.evaluation_public)) \
                .join(Submission) \
                .group_by(Submission.user_id) \
                .order_by(Evaluation.evaluation_public.desc()) \
                .all()

            score = request.args.get("score") # Успешная загрузка данных
            participants = [(user_id, competition_tools.score_mapper(score)) for user_id, score in participants]
            with_success = request.args.get("with_success")
            error_message = request.args.get("error_message")

            if score:
                try:
                    score = competition_tools.score_mapper(float(score))
                except: # Just in case someone passes something nasty for `score`
                    score = False

            # with_success = request.args["error_message"]
            return render_template("index.html",
                                   score=score,
                                   participants=participants,
                                   can_submit=True,
                                   with_success=with_success,
                                   close_time=stage_handler.close_time,
                                   is_closed=stage_handler.is_closed(),
                                   error_message=error_message)

    except Exception as ex:
        traceback.print_stack()
        traceback.print_exc()
        return redirect(url_for('error', error_message=ex))
        # return render_template("index.html")


####################
# update submissions
####################
@application.route('/update_submissions', methods=["GET", "POST"])
def update_submissions():
    if not api_auth.is_valid(session["api_key"]):
        raise Exception("Недопустимый ключ API")

    user_id = api_auth.get_user(session["api_key"])
    checked_submission_ids = [int(checked_s_id) for checked_s_id in request.form]
    # checked_submission_ids = [int(checked_s_id) for checked_s_id in request.form.getlist('options')]
    print("checked_submission_ids:", checked_submission_ids)

    try:
        user_evals = db.session.query(Evaluation).join(Submission).filter_by(user_id=user_id).all()

        print("user_evals:", user_evals)

        for e in user_evals:
            e.private_check = False
            if e.submission_id in checked_submission_ids:
                e.private_check = True

        db.session.commit()
        return redirect('/?with_success=Данные успешно были обновлены')

    except Exception as ex:
        db.session.rollback()
        traceback.print_stack()
        traceback.print_exc()
        return redirect('/?with_success=False')


###################
# final leaderboard
###################
@application.route('/fleaderboard', methods=["GET"])
def fleaderboard():

    if not stage_handler.is_closed():
        return redirect('/')

    try:
        user_id = None
        api_key = request.args.get("api_key", None)
        if api_key is not None:
            user_id = get_user_id(api_key)
            application.logger.info(f"Received request to final leaderboard page by user_id '{user_id}'.")

    except Exception as ex:
        traceback.print_stack()
        traceback.print_exc()
        return redirect(url_for('error', error_message=ex))

    # if ((user_id is None) or (user_id not in [app.config['ADMIN_USER_ID']])):
    #     return redirect(url_for("leaderboard"))

    participants = []

    print(db.Column(db.DateTime, default=datetime.utcnow, nullable=False))
    print(db.session.query(Submission, func.max(Evaluation.evaluation_private)).join(Submission)\
          .group_by(Submission.user_id).order_by(Evaluation.evaluation_private.desc())\
          .filter(Submission.timestamp < stage_handler.close_time, Evaluation.private_check.is_(True))
          .all())

    # Get the max private score corresponding for the peope that have selected aty least one solution
    participants_select = db.session \
        .query(Submission.user_id, func.max(Evaluation.evaluation_private)) \
        .join(Submission) \
        .group_by(Submission.user_id) \
        .order_by(Evaluation.evaluation_private.desc()) \
        .filter(Submission.timestamp < stage_handler.close_time, Evaluation.private_check.is_(True)) \
        .all()

    print("participants_select:", participants_select)
    participants += participants_select

    # Get the people that did not select any solutions sorted by user_id, evaluation_public and timestamp
    participants_not_select = db.session \
        .query(Submission.user_id, Evaluation.evaluation_public, Evaluation.evaluation_private) \
        .join(Submission) \
        .filter(Submission.timestamp < stage_handler.close_time,
                Submission.user_id.notin_([u_id for u_id, _ in participants_select])) \
        .order_by(Submission.user_id.desc(), Evaluation.evaluation_public.desc(), Submission.timestamp.desc()) \
        .all()

    print("participants_not_select:", participants_not_select)

    # Get the private score corresponding to the max public score for the people that did not select any solutions
    # Since data is sorted desc, the first entry for each user is the score to take
    u_placeholder = set()
    for pns in participants_not_select:
        if pns[0] not in u_placeholder:
            participants.append((pns[0], pns[2]))
        u_placeholder.add(pns[0])

    # Sort the scores
    participants = sorted(participants, key=lambda x: x[1], reverse=True)
    participants = [(user_id, competition_tools.score_mapper(round(score, 5))) for user_id, score in participants]

    return render_template("finalResult.html",
                           participants=participants,
                           close_time=stage_handler.close_time,
                           is_closed=stage_handler.is_closed())

################
# Show evaluate score
################
# @application.route('/show_evaluate_score', methods=["GET"])
# def show_evaluate_score():
#     return render_template('evaluation_score.html',
#                            pub_score=request.args.get("pub_score"),
#                            priv_score=request.args.get("priv_score"),
#                            baseline=int(request.args.get("baseline")))

################
# Evaluate
################
@application.route('/evaluate', methods=["GET"])
def evaluate():
    try:
        api_key = request.args.get("api_key")
        user_id = get_user_id(api_key)

        if (user_id not in [application.config['ADMIN_USER_ID'], application.config['BASELINE_USER_ID']]) and\
                (not stage_handler.can_submit()):
            return redirect(url_for('leaderboard'))
        else:

            submission_id = request.args.get("submission_id")
            submission = Submission.query.filter_by(id=submission_id, user_id=user_id).first()
            public_score, private_score = eval_public_private(submission.filename, application.config['TEST_FILE_PATH'])
            if not submission:
                # not found!
                raise Exception("Не удалось отправить данные!")

            # if user_id == app.config['ADMIN_USER_ID']:
            if user_id == application.config['ADMIN_USER_ID']:
                return redirect(
                    url_for("show_evaluate_score", pub_score=public_score, priv_score=private_score, baseline=0))
            else:
                evaluation = Evaluation(submission=submission, evaluation_public=public_score, evaluation_private=private_score)
                db.session.add(evaluation)
                db.session.commit()

                if user_id == application.config['BASELINE_USER_ID']:
                # if user_id:
                    return redirect(
                        url_for("show_evaluate_score", pub_score=public_score, priv_score=private_score, baseline=1))
                else:
                    submissions_left = int(application.config['MAX_NUMBER_SUBMISSIONS'] - competition_tools.get_user_submissions_number(user_id=user_id, db=db))

                    # return redirect(url_for('leaderboard',
                    #                         score=public_score,
                    #                         highlight=user_id,
                    #                         left=submissions_left
                    #                         ))

                    return redirect('/?with_success=Данные успешно были добавлены!')

    except Exception as ex:
        traceback.print_stack()
        traceback.print_exc()
        return redirect(url_for('error', error_message=ex))

################
# Upload
################
@application.route('/upload', methods=["POST"])
def upload():
    try:
        api_key = request.form.get("api_key", None)
        user_id = get_user_id(api_key)  # This will be stored in the Submissions table

        # TODO Handle this. Doing so, a student who loaded the page before the deadline can still perform the submission
        if (user_id not in [application.config['ADMIN_USER_ID'], application.config['BASELINE_USER_ID']]) and\
                (not stage_handler.can_submit()):
            return redirect('/')
        else:

            # Check submit request id
            if ("submit_request_id" not in session.keys()) or \
                    (session["submit_request_id"] != request.form.get('submitRequestId', None)):
                error_message = "Неправильный запрос. Используйте веб-страницу формы для загрузки решения или попробуйте перезагрузить страницу!"
                raise Exception(error_message)

            # Save submitted solution
            if request.method == 'POST':
                latest_submission = db.session.query(func.max(Submission.timestamp)).filter(Submission.user_id == user_id).first()[0]
                now = datetime.utcnow()

                if user_id not in [application.config['ADMIN_USER_ID'], application.config['BASELINE_USER_ID']]:

                    if latest_submission and (now - latest_submission).total_seconds() < application.config['TIME_BETWEEN_SUBMISSIONS']:
                        delta = max(5, int(application.config['TIME_BETWEEN_SUBMISSIONS'] - (now - latest_submission).total_seconds())) # avoid messages such as "try again in 0/1/2 seconds" (TODO remove magic number 5)
                        raise Exception(f"Интервал между загрузками данных не должен превышать 1 часа!")

                    n_submissions = competition_tools.get_user_submissions_number(user_id=user_id, db=db)
                    if n_submissions >= application.config['MAX_NUMBER_SUBMISSIONS']:
                        raise Exception(f"Вы превышаете максимальное количество отправлений {application.config['MAX_NUMBER_SUBMISSIONS']} попыток. "
                                        f"Вам больше не разрешается отправлять какое-либо решение")

                # check if the post request has the file part
                if 'submittedSolutionFile' not in request.files:
                    error_message = 'Нет части файла'
                    raise Exception(error_message)

                file = request.files['submittedSolutionFile']
                if not file:
                    error_message = 'Ошибка при загрузке файла решения.'
                    raise Exception(error_message)

                # if user does not select file, browser also
                # submit an empty part without filename
                if file.filename == '':
                    error_message = 'Не выбранн файл'
                    raise Exception(error_message)

                if competition_tools.allowed_file(file.filename) and \
                        competition_tools.check_file(file, application.config['TEST_FILE_PATH']):



                    timestamp = competition_tools.get_timestamp()
                    new_file_name = f"{timestamp}_{user_id}.csv"
                    output_file = os.path.join(application.config['UPLOAD_FOLDER'], new_file_name)
                    # we are reading the stream when checking the file, so we need to go back to the start
                    file.stream.seek(0)
                    file.save(output_file)
                    submission = Submission(user_id=user_id, filename=output_file)
                    db.session.add(submission)
                    db.session.commit()
                    # By passing api_key, we can later check that the user calling /evaluate
                    # is the same that has made the submission
                    return redirect(url_for('evaluate', submission_id=submission.id, api_key=api_key))
                    # return redirect('/?with_success=Данные успешно были добавлены!')
                else:
                    raise Exception("Ты не должен быть здесь!")

    except Exception as ex:
        traceback.print_stack()
        traceback.print_exc()
        return redirect(url_for('error', error_message=ex))


################
# Submit
################
@application.route('/submit', methods=["GET"])
def submit():

    if stage_handler.is_closed():
        return redirect('/')

    try:
        user_id = None
        api_key = request.args.get("api_key", None)
        if api_key is not None:
            user_id = get_user_id(api_key)
            application.logger.info(f"Received request to submission page by user_id '{user_id}'.")

        if ((user_id is None) or (user_id not in [application.config['ADMIN_USER_ID']])) and\
                (not stage_handler.can_submit()):
            return redirect(url_for("leaderboard"))
        else:
            submit_request_id = secrets.token_hex()
            session["submit_request_id"] = submit_request_id
            return render_template("loadData.html",
                                   submit_request_id=submit_request_id,
                                   close_time=stage_handler.close_time,
                                   is_closed=stage_handler.is_closed())

    except Exception as ex:
        traceback.print_stack()
        traceback.print_exc()
        return redirect(url_for('error', error_message=ex))


if __name__ == '__main__':
    application.run(host='0.0.0.0', port=3030, debug=True)
