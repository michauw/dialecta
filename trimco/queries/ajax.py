import json, re, csv

from morphology.models import *
from corpora.models import *
from corpora.elan_tools import ElanObject
from info.models import *

from django_ajax.decorators import ajax
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import redirect
from django.core.urlresolvers import reverse


@csrf_exempt
def query_ajax(request):

  request.session['query_dic'] = request.POST.dict()
  request.session['raw_keys_dic'] = {k: request.POST.getlist(k) for k in request.POST.dict().keys()} 
  
  response = {}
  return HttpResponse(json.dumps(response))

@csrf_exempt
def download(request):
  return query(request.session.pop('query_dic'),request.session.pop('raw_keys_dic')).result_to_csv()

class query:

  def __init__(self, query_dic, raw_keys_dic):

    print(query_dic, raw_keys_dic)

    self.query_dic = query_dic
    self.file_conditions = []
    self.morph_conditions = []
    self.result = []
    status_dict = {'true':True, 'false':False}
    i = 0
    c = query_condition()
    for raw_key in sorted(self.query_dic.keys()):
      key_structure = [re.sub('\[|\]', '', x) for x in re.split('(\[[0-9]+\])', raw_key)]
      key = key_structure[-1]
      if key_structure[0] == 'request_data':
        if i != key_structure[1]:
          if c.arg != {}:
            c = self.add_condition(c)
        i = key_structure[1]
        value = self.query_dic[raw_key]
        if 'morph_lst' in raw_key:
          value = [(v.split('=')[0], status_dict[v.split('=')[1]]) for v in raw_keys_dic[raw_key]]
        c.add_property(key, value)
    self.add_condition(c)
    self.query_files()
    self.process_transcriptions()

  def add_condition(self, c):
    
    if c.arg == {}:
      return c
    if c.type == 'morph':
      self.morph_conditions.append(c)
    elif c.type == 'file':
      self.file_conditions.append(c)
    return query_condition()

  def query_files(self):

    qs = Recording.objects.all()
    for c in self.file_conditions:
      q = c.get_queryset()
      if list(q)!=[]:
        qs.filter(id__in=q) #exclude
    self.recordings = qs

  def result_to_csv(self):

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="query_result.csv"'

    writer = csv.writer(response)
    for r in self.result:
      writer.writerow([r['token'],r['normalization'],r['lemma'],r['annotation'],r['participant'],r['file'],r['tier name'],r['index in tier']])
    return response
      
  def process_transcriptions(self):

    for recording_obj in self.recordings:
      if recording_obj.data:
        elan_obj = ElanObject(recording_obj.data.path)
        for annot_data in elan_obj.annot_data_lst:
          self.process_tier(elan_obj, annot_data, recording_obj.__str__())

  def process_tier(self, elan_obj, annot_data, file_name):

    tier_name = annot_data[3]
    tier_obj = elan_obj.get_tier_obj_by_name(tier_name)

    if tier_obj.attributes['TIER_ID']!='comment':
      tokens_lst = [x for x in re.split('([ ])', annot_data[2]) if x != ' ']
      normz_tokens_dict = self.get_additional_tags_dict(elan_obj, tier_name+'_standartization', annot_data[0], annot_data[1])
      annot_tokens_dict = self.get_additional_tags_dict(elan_obj, tier_name+'_annotation', annot_data[0], annot_data[1])
      i = 0
      while i < len(tokens_lst):
        if i in normz_tokens_dict.keys():
          token_dict = self.get_token_dict(tokens_lst, normz_tokens_dict, annot_tokens_dict, i)
          if self.query_morph(token_dict)==True:
            token_dict['tier name'] = tier_obj.name
            token_dict['index in tier'] = '%s/%s' %(i+1, len(tokens_lst)+1)
            token_dict['participant'] = tier_obj.attributes['PARTICIPANT']
            token_dict['file'] = file_name
            self.result.append(token_dict)
        i+=1

  def query_morph(self, token_dict):

    for conditions_obj in self.morph_conditions:
      for c, v in conditions_obj.get_morph():
        if c not in token_dict['annotation'].split('-') and v == True:
          return False
        if c in token_dict['annotation'].split('-') and v == False:
          return False
    return True
      
  def get_token_dict(self, tokens_lst, normz_tokens_dict, annot_tokens_dict, i):

    token_dict = {}
    token_dict['token'] = tokens_lst[i]
    token_dict['normalization'] = normz_tokens_dict[i][0]
    token_dict['lemma'] = annot_tokens_dict[i][0]
    token_dict['annotation'] = annot_tokens_dict[i][1]
    return token_dict

  def get_additional_tags_dict(self, elan_obj, tier_name, start, end):

    tokens_dict = {}
    try:
      nrm_annot_lst = elan_obj.Eaf.get_annotation_data_at_time(tier_name, (start+end) / 2 )
      if nrm_annot_lst != []:
        nrm_annot = nrm_annot_lst[0][-1]
        for el in ([el.split(':') for el in nrm_annot.split('|')]):
          tokens_dict[int(el[0])] = el[1:]
      return tokens_dict
    except KeyError:
      return tokens_dict

class query_condition:

  def __init__(self):
    self.arg = {}

  def add_property(self, key, value):
    if value == '':
      value = None
    self.arg[key] = value

  @property
  def type(self):

    if 'morph_lst' in self.arg.keys():
      return 'morph'
    elif 'pk' in self.arg.keys():
      if self.arg['pk']!=None:
        return 'file'
    return None

  def get_queryset(self):

    if self.type == 'morph':
      return self.get_morph()
    if self.type == 'file':
      model, pk = self.arg['model'], self.arg['pk']
      if model in ['dialect', 'speaker']:
        kwargs = {'{0}'.format('to_%s' %(model)): pk,}
      elif model in ['location']:
        kwargs = {'{0}'.format('%s' %(model)): pk,}
      elif model in ['language']:
        kwargs = {'to_dialect__to_language': pk,}
      return Recording.objects.filter(**kwargs)

  def get_morph(self):
    
    return self.arg['morph_lst']



