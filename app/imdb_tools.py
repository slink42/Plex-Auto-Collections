import re
import requests
import math
import sys
from urllib.parse import urlparse
from lxml import html
from tmdbv3api import TMDb
from tmdbv3api import Movie
from tmdbv3api import List
from tmdbv3api import TV
from tmdbv3api import Collection
from tmdbv3api import Person
import config_tools
import trakt


def imdb_get_movies(config_path, plex, data):
    tmdb = TMDb()
    movie = Movie()
    tmdb.api_key = config_tools.TMDB(config_path).apikey
    imdb_url = data
    if imdb_url[-1:] == " ":
        imdb_url = imdb_url[:-1]
    imdb_map = {}
    library_language = plex.Library.language
    if "/search/" in imdb_url:
        if "&count=" in imdb_url:
            imdb_url = re.sub("&count=\d+", "&count=100", imdb_url)
        else:
            imdb_url = imdb_url + "&count=100"
    try:
        r = requests.get(imdb_url, headers={'Accept-Language': library_language})
    except requests.exceptions.MissingSchema:
        return
    tree = html.fromstring(r.content)
    title_ids = tree.xpath("//div[contains(@class, 'lister-item-image')]"
                           "//a/img//@data-tconst")
    if "/search/" in imdb_url:
        results = re.search('<span>\\d+-\\d+ of \\d+ titles.</span>', str(r.content))
        total = re.findall('(\\d+)', results.group(0))[2]
    else:
        results = re.search('(?<=<div class="desc lister-total-num-results">).*?(?=</div>)', str(r.content))
        total = re.search('.*?(\\d+)', results.group(0)).group(1)

    for i in range(1, math.ceil(int(total) / 100)):
        try:
            if "/search/" in imdb_url:
                r = requests.get(imdb_url + '&start={}'.format(i * 100 + 1), headers={'Accept-Language': library_language})
            else:
                r = requests.get(imdb_url + '?page={}'.format(i + 1), headers={'Accept-Language': library_language})
        except requests.exceptions.MissingSchema:
            return
        tree = html.fromstring(r.content)
        title_ids.extend(tree.xpath("//div[contains(@class, 'lister-item-image')]"
                                    "//a/img//@data-tconst"))
    if title_ids:
        for m in plex.Library.all():
            try:
                if 'themoviedb://' in m.guid:
                    if not tmdb.api_key == "None":
                        tmdb_id = m.guid.split('themoviedb://')[1].split('?')[0]
                        tmdbapi = movie.details(tmdb_id)
                        imdb_id = tmdbapi.imdb_id
                    else:
                        imdb_id = None
                elif 'imdb://' in m.guid:
                    imdb_id = m.guid.split('imdb://')[1].split('?')[0]
                else:
                    imdb_id = None
            except:
                imdb_id = None

            if imdb_id and imdb_id in title_ids:
                imdb_map[imdb_id] = m
            else:
                imdb_map[m.ratingKey] = m

        matched_imbd_movies = []
        missing_imdb_movies = []
        for imdb_id in title_ids:
            movie = imdb_map.pop(imdb_id, None)
            if movie:
                matched_imbd_movies.append(plex.Server.fetchItem(movie.ratingKey))
            else:
                missing_imdb_movies.append(imdb_id)

        return matched_imbd_movies, missing_imdb_movies

def tmdb_get_movies(config_path, plex, data, is_list=False):
    try:
        tmdb_id = re.search('.*?(\\d+)', data)
        tmdb_id = tmdb_id.group(1)
    except AttributeError:  # Bad URL Provided
        return
    t_movs = []
    t_movie = Movie()
    t_movie.api_key = config_tools.TMDB(config_path).apikey  # Set TMDb api key for Movie
    if t_movie.api_key == "None":
        raise KeyError("Invalid TMDb API Key")

    tmdb = List() if is_list else Collection()
    tmdb.api_key = t_movie.api_key
    t_col = tmdb.details(tmdb_id)

    if is_list:
        try:
            for tmovie in t_col:
                if tmovie.media_type == "movie":
                    t_movs.append(tmovie.id)
        except:
            raise ValueError("| Config Error: TMDb List: {} not found".format(tmdb_id))
    else:
        try:
            for tmovie in t_col.parts:
                t_movs.append(tmovie['id'])
        except AttributeError:
            try:
                t_movie.details(tmdb_id).imdb_id
                t_movs.append(tmdb_id)
            except:
                raise ValueError("| Config Error: TMDb ID: {} not found".format(tmdb_id))


    # Create dictionary of movies and their guid
    # GUIDs reference from which source Plex has pulled the metadata
    p_m_map = {}
    p_movies = plex.Library.all()
    for m in p_movies:
        guid = m.guid
        if "themoviedb://" in guid:
            guid = guid.split('themoviedb://')[1].split('?')[0]
        elif "imdb://" in guid:
            guid = guid.split('imdb://')[1].split('?')[0]
        else:
            guid = "None"
        p_m_map[m] = guid

    matched = []
    missing = []
    # We want to search for a match first to limit TMDb API calls
    # Too many rapid calls can cause a momentary block
    # If needed in future maybe add a delay after x calls to let the limit reset
    for mid in t_movs:  # For each TMBd ID in TMBd Collection
        match = False
        for m in p_m_map:  # For each movie in Plex
            if "tt" not in p_m_map[m] != "None":  # If the Plex movie's guid does not start with tt
                if int(p_m_map[m]) == int(mid):
                    match = True
                    break
        if not match:
            imdb_id = t_movie.details(mid).imdb_id
            for m in p_m_map:
                if "tt" in p_m_map[m]:
                    if p_m_map[m] == imdb_id:
                        match = True
                        break
        if match:
            matched.append(m)
        else:
            # Duplicate TMDb call?
            missing.append(t_movie.details(mid).imdb_id)

    return matched, missing

def get_tautulli(config_path, plex, data):
    tautulli = config_tools.Tautulli(config_path)
    type = config_tools.check_for_attribute(data, "list_type", parent="tautulli", test_list=["popular", "watched"], options="| \tpopular (Most Popular List)\n| \twatched (Most Watched List)", throw=True, save=False)
    time_range = config_tools.check_for_attribute(data, "list_days", parent="tautulli", type="int", default=30, save=False)
    max = config_tools.check_for_attribute(data, "list_size", parent="tautulli", type="int", default=10, save=False)
    buffer = config_tools.check_for_attribute(data, "list_buffer", parent="tautulli", type="int", default=20, save=False)
    stats_count = max + buffer

    response = requests.get("{}/api/v2?apikey={}&cmd=get_home_stats&time_range={}&stats_count={}".format(tautulli.url, tautulli.apikey, time_range, stats_count)).json()
    stat_id = ("popular" if type == "popular" else "top") + "_" + ("movies" if plex.library_type == "movie" else "tv")

    items = None
    for entry in response['response']['data']:
        if entry['stat_id'] == stat_id:
            items = entry['rows']
            break
    if items is None:
        sys.exit("| No Items found in the response")

    section_id = None
    response = requests.get("{}/api/v2?apikey={}&cmd=get_library_names".format(tautulli.url, tautulli.apikey)).json()
    for entry in response['response']['data']:
        if entry['section_name'] == plex.library:
            section_id = entry['section_id']
            break
    if section_id is None:
        sys.exit("| No Library named {} in the response".format(plex.library))

    matched = []
    missing = []
    count = 0
    for item in items:
        if item['section_id'] == section_id and count < max:
            matched.append(plex.Library.fetchItem(item['rating_key']))
            count = count + 1

    return matched, missing

def get_tvdb_id_from_tmdb_id(id):
    lookup = trakt.Trakt['search'].lookup(id, 'tmdb', 'show')
    if lookup:
        if isinstance(lookup, list):
            return trakt.Trakt['search'].lookup(id, 'tmdb', 'show')[0].get_key('tvdb')
        else:
            return trakt.Trakt['search'].lookup(id, 'tmdb', 'show').get_key('tvdb')
    else:
        return None

def tmdb_get_shows(config_path, plex, data, is_list=False):
    config_tools.TraktClient(config_path)
    try:
        tmdb_id = re.search('.*?(\\d+)', data)
        tmdb_id = tmdb_id.group(1)
    except AttributeError:  # Bad URL Provided
        return
    t_tvs = []
    t_tv = TV()
    t_tv.api_key = config_tools.TMDB(config_path).apikey  # Set TMDb api key for Movie
    if t_tv.api_key == "None":
        raise KeyError("Invalid TMDb API Key")

    if is_list:
        tmdb = List()
        tmdb.api_key = t_tv.api_key
        try:
            t_col = tmdb.details(tmdb_id)
            for ttv in t_col:
                if ttv.media_type == "tv":
                    t_tvs.append(ttv.id)
        except:
            raise ValueError("| Config Error: TMDb List: {} not found".format(tmdb_id))
    else:
        try:
            t_tv.details(tmdb_id).number_of_seasons
            t_tvs.append(tmdb_id)
        except:
            raise ValueError("| Config Error: TMDb ID: {} not found".format(tmdb_id))

    p_tv_map = {}
    for item in plex.Library.all():
        guid = urlparse(item.guid)
        item_type = guid.scheme.split('.')[-1]
        if item_type == 'thetvdb':
            tvdb_id = guid.netloc
        elif item_type == 'themoviedb':
            tvdb_id = get_tvdb_id_from_tmdb_id(guid.netloc)
        else:
            tvdb_id = None
        p_tv_map[item] = tvdb_id

    matched = []
    missing = []
    for mid in t_tvs:
        match = False
        tvdb_id = get_tvdb_id_from_tmdb_id(mid)
        for t in p_tv_map:
            if p_tv_map[t] and "tt" not in p_tv_map[t] != "None":
                if int(p_tv_map[t]) == int(tvdb_id):
                    match = True
                    break
        if match:
            matched.append(t)
        else:
            missing.append(tvdb_id)

    return matched, missing

def tvdb_get_shows(config_path, plex, data, is_list=False):
    config_tools.TraktClient(config_path)
    try:
        id = re.search('(\\d+)', data)
        id = id.group(1)
    except AttributeError:
        raise ValueError("| Config Error: TVDb ID: {} is invalid it must be a number".format(data))

    p_tv_map = {}
    for item in plex.Library.all():
        guid = urlparse(item.guid)
        item_type = guid.scheme.split('.')[-1]
        if item_type == 'thetvdb':
            tvdb_id = guid.netloc
        elif item_type == 'themoviedb' and TraktClient.valid:
            tvdb_id = get_tvdb_id_from_tmdb_id(guid.netloc)
        else:
            tvdb_id = None
        p_tv_map[item] = tvdb_id

    matched = []
    missing = []
    match = False
    for t in p_tv_map:
        if p_tv_map[t] and "tt" not in p_tv_map[t] != "None":
            if int(p_tv_map[t]) == int(id):
                match = True
                break
    if match:
        matched.append(t)
    else:
        missing.append(id)

    return matched, missing

def tmdb_get_summary(config_path, data, type):
    # Instantiate TMDB objects
    collection = Collection()
    collection.api_key = config_tools.TMDB(config_path).apikey
    collection.language = config_tools.TMDB(config_path).language

    media = Movie() if config_tools.Plex(config_path).library_type == "movie" else TV()
    media.api_key = config_tools.TMDB(config_path).apikey
    media.language = config_tools.TMDB(config_path).language

    person = Person()
    person.api_key = collection.api_key
    person.language = collection.language

    # Return object based on type
    if type == "overview":
        try:
            return collection.details(data).overview
        except:
            return media.details(data).overview
    elif type == "biography":
        return person.details(data).biography
    elif type == "poster_path":
        try:
            return collection.details(data).poster_path
        except:
            return media.details(data).poster_path
    elif type == "profile_path":
        return person.details(data).profile_path
    elif type == "backdrop_path":
        try:
            return collection.details(data).backdrop_path
        except:
            return media.details(data).backdrop_path
    else:
        raise RuntimeError("type not yet supported in tmdb_get_summary")
