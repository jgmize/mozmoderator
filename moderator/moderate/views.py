from django_browserid import get_audience, verify, BrowserIDException
from django_browserid.auth import default_username_algo
from django_browserid.views import Verify

from django.db.models import Count
from django.core.urlresolvers import reverse
from django.contrib import auth, messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import HttpResponse
from django.shortcuts import render, redirect
from django.utils import simplejson

from moderator.moderate.mozillians import is_vouched, BadStatusCodeError
from moderator.moderate.models import MozillianProfile, Event, Question, Vote
from moderator.moderate.forms import QuestionForm


class CustomVerify(Verify):
    def form_valid(self, form):
        """Custom mozillians login form validation"""
        self.assertion = form.cleaned_data['assertion']
        self.audience = get_audience(self.request)
        result = verify(self.assertion, self.audience)

        try:
            _is_valid_login = False
            if result:
                if User.objects.filter(email=result['email']).exists():
                    _is_valid_login = True
                else:
                    data = is_vouched(result['email'])
                    if data and data['is_vouched']:
                        _is_valid_login = True
                        user = User.objects.create_user(
                            username=default_username_algo(data['email']),
                            email=data['email'])
                        MozillianProfile.objects.create(
                            user=user, username=data['username'],
                            avatar_url=data['photo'])

            if _is_valid_login:
                try:
                    self.user = auth.authenticate(assertion=self.assertion,
                                                  audience=self.audience)
                    auth.login(self.request, self.user)

                except BrowserIDException as e:
                    return self.login_failure(e)

                if self.user and self.user.is_active:
                    return self.login_success()

        except BadStatusCodeError:
            msg = ('Email (%s) authenticated but unable to '
                   'connect to Mozillians to see if you are vouched'
                   % result['email'])
            messages.warning(self.request, msg)
            return self.login_failure()

        messages.error(self.request, ('Login failed. Make sure you are using '
                                      'a valid email address and you are '
                                      'a vouched Mozillian.'))
        return self.login_failure()


def main(request):
    """Render main page."""
    if request.user.is_authenticated():
        events = Event.objects.all()
        return render(request, 'index.html', {
                               'events': events,
                               'user': request.user})
    else:
        return render(request, 'index.html', {'user': request.user})


@login_required
def event(request, e_slug):
    """Render event questions."""
    event = Event.objects.get(slug=e_slug)

    questions = (Question.objects.filter(event=event)
                 .annotate(vote_count=Count('votes'))
                 .order_by('-vote_count'))

    if request.POST:
        question_form = QuestionForm(request.POST)

        if question_form.is_valid():
            question = question_form.save(commit=False)
            question.asked_by = request.user
            question.event = event
            question.save()
            return redirect(reverse('event', kwargs={'e_slug': event.slug}))
    else:
        question_form = QuestionForm()

    return render(request, 'questions.html',
                  {'user': request.user,
                   'event': event,
                   'questions': questions,
                   'q_form': question_form})


@login_required
def upvote(request, q_id):
    """Upvote question"""

    question = Question.objects.get(pk=q_id)

    if request.is_ajax():
        vote, created = Vote.objects.get_or_create(user=request.user,
                                                   question=question)
        response_dict = {}
        response_dict.update({'current_vote_count': question.votes.count()})

        return HttpResponse(simplejson.dumps(response_dict),
                            mimetype='application/javascript')

    return event(request, question.event.slug)
