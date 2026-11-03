"""Synthetic retrieval contracts; no personal books or production database."""
import contextlib
import copy
import hashlib
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import build_index
import research_findings
import taira_search
import daily_five
from research_profile import effective_search_mode, load_research_profile
from source_discovery import discovery_evidence, discover_sources, document_group, spread_indices


class DiscoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        work = Path(__file__).resolve().parents[1] / 'work'
        work.mkdir(exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(prefix='discovery-tests-', dir=work)
        cls.root = Path(cls.temp.name)
        corpus = cls.root / 'corpus'
        texts = {
            'Collection/unknown.txt': 'An unnamed cook fell asleep while holding a pastry. A servant took the nodding as permission, ate it, and explained the missing pastry when the cook woke up.',
            'Collection/known.txt': 'Ada inspected the royal household kitchen and ordered the missing grain to be replaced. A messenger brought back a receipt confirming that the sacks had arrived.',
            'Banned/other.txt': 'An unnamed potter left a bowl outside overnight. A neighbour mistook it for a gift, filled it with beans, and returned it in the morning with a thank-you note.',
            'Articles/note.md': 'A synthetic scholarly interpretation of royal household inventories compares several accounting traditions and explains the limits of drawing conclusions from surviving lists.',
            'Collection/reference.txt': 'Bibliography\n\nAda, Collected Letters, volume one, published in an unnamed city. This reference is a catalogue entry and contains no incident involving its author.',
            'Collection/unreadable.txt': 'Short fragment.',
        }
        for name, text in texts.items():
            path = corpus / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding='utf-8')
        cls.database = cls.root / 'index.sqlite3'
        source_types = cls.root / 'source-types.json'
        source_types.write_text(json.dumps({
            'historical': [], 'literary': [],
            'scholarship': ['Articles'], 'other': []
        }), encoding='utf-8')
        cls.used = cls.root / 'used.csv'
        cls.used.write_text('id,type,persons,topics,short_description,source,date_used\n', encoding='utf-8')
        cls.publications = cls.root / 'publications'
        cls.publications.mkdir()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = build_index.main([str(corpus), '--db', str(cls.database),
                '--log', str(cls.root / 'build.log'),
                '--source-types', str(source_types)])
        assert code == 0
        cls.profile = dict(schema_version=1, name='Synthetic discovery', research_area='Household history',
            result_language='en', max_results=1,
            interests=[dict(id='household', label='Royal households', terms=['royal household'], weight=1)],
            focus_people=[dict(name='Ada', aliases=['Ada'])],
            material_types=['historical', 'literary', 'scholarship', 'other'],
            include_sources=[], exclude_sources=['Banned'],
            finding_preferences=dict(preferred_kinds=['pastry'], include_unlisted_people=True,
                                     avoid_person_repetition=True, notes=''))

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_preview(self, mode='open', changes=None, previous=None, batch_size=10,
                    used_path=None, publications_path=None, database=None,
                    automatic_resume=False):
        profile = copy.deepcopy(self.profile)
        if mode is not None:
            profile['search_mode'] = mode
        if changes:
            profile.update(changes)
        path = self.root / 'profile.json'
        path.write_text(json.dumps(profile), encoding='utf-8')
        output = self.root / 'preview.json'
        if previous:
            previous_path = self.root / 'previous.json'
            previous_path.write_text(json.dumps(previous), encoding='utf-8')
        args = ['research-findings', '--db', str(database or self.database), '--profile', str(path),
                '--used-finds', str(used_path or self.used), '--output', str(output), '--preview',
                '--batch-size', str(batch_size)]
        if not automatic_resume:
            args += ['--resume-exploration-from', str(publications_path or self.publications)]
        if previous:
            args += ['--continue-from', str(previous_path)]
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as err:
            code = taira_search.main(args)
        self.assertEqual(code, 0, err.getvalue())
        return json.loads(output.read_text(encoding='utf-8'))

    def register_checkpoint(self, result, number, publications=None, used=None):
        publications = publications or self.publications
        used = used or self.used
        manifest = publications / f'edition-{number}.json'
        manifest.write_text(json.dumps({
            'publication_id': f'edition-{number}',
            'exploration_checkpoint': result['exploration_checkpoint'],
            'cards': [{
                'id': f'ch_published_{number}', 'type': 'event',
                'short_description': f'Published test card {number}',
                'source': 'Synthetic publication',
                'card_markdown': f'### Published test card {number}',
            }],
        }), encoding='utf-8')
        daily_five.record_publication_from_json(manifest, used)
        return manifest

    @staticmethod
    def candidates(result):
        return result['final'] + result['alternates']

    def test_unknown_story_without_interest_terms_reaches_editor_and_keeps_evidence(self):
        result = self.run_preview()
        story = next(c for c in self.candidates(result) if c['filename'] == 'unknown.txt')
        self.assertIsNone(story['primary_topic'])
        self.assertEqual(story['topics'], [])
        self.assertIn('source_exploration', story['retrieval']['methods'])
        self.assertTrue(story['retrieval']['preference_probe_hit'])
        self.assertEqual(story['scope_review']['status'], 'pending')
        self.assertIn('pastry', story['what_happened'])
        self.assertTrue(story['verified_context']['chunks'][0]['text'])
        packet = research_findings.build_editorial_packet(result)
        compact = next(c for c in self.candidates(packet) if c['chunk_id'] == story['chunk_id'])
        self.assertIn('retrieval', compact)
        self.assertIn('scope_review', compact)
        self.assertNotIn('verified_context', compact)
        self.assertEqual(packet['profile']['finding_preferences']['preferred_kinds'], ['pastry'])

    def test_hard_excludes_and_material_types_apply_to_discovery(self):
        result = self.run_preview(changes={'material_types': ['other']})
        self.assertTrue(self.candidates(result))
        self.assertTrue(all(c['source'] != 'Banned' and c['source_type'] == 'other' for c in self.candidates(result)))
        info = result['coverage']['discovery']['sources']
        self.assertEqual(info['Banned/other.txt']['filtered']['exclude_sources'], 1)
        self.assertEqual(info['Articles/note.md']['filtered']['material_type'], 1)
        included = self.run_preview(changes={'include_sources': ['Collection']})
        self.assertTrue(all(c['source'] == 'Collection' for c in self.candidates(included)))

    def test_focused_people_excludes_unknown_and_bibliographic_name_only(self):
        result = self.run_preview('focused_people')
        rows = self.candidates(result)
        self.assertTrue(rows)
        self.assertTrue(all(c['filename'] == 'known.txt' for c in rows))
        self.assertTrue(all(c['scope_review']['search_mode'] == 'focused_people' for c in rows))
        self.assertIn('name alone is insufficient', rows[0]['scope_review']['required'])

    def test_switch_modes_without_indexing_and_legacy_policy_is_preserved(self):
        before = self.database.read_bytes()
        strict = self.run_preview('focused_people')
        opened = self.run_preview('open')
        self.assertGreater(len(self.candidates(opened)), len(self.candidates(strict)))
        self.assertEqual(self.database.read_bytes(), before)
        legacy_profile = copy.deepcopy(self.profile)
        legacy_profile['finding_preferences']['include_unlisted_people'] = False
        path = self.root / 'legacy.json'
        path.write_text(json.dumps(legacy_profile))
        original = path.read_bytes()
        loaded = load_research_profile(path)
        self.assertNotIn('search_mode', loaded)
        self.assertEqual(effective_search_mode(loaded), 'focused_people')
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(effective_search_mode(dict(loaded, search_mode='open')), 'open')

    def test_explicit_person_mode_requires_people(self):
        payload = dict(self.profile, search_mode='focused_people', focus_people=[])
        path = self.root / 'invalid.json'
        path.write_text(json.dumps(payload))
        with self.assertRaisesRegex(ValueError, 'focus_people'):
            load_research_profile(path)

    def test_continuation_is_disjoint_and_single_slot_routes_progress(self):
        previous = None
        ids = set()
        names = set()
        for _ in range(8):
            result = self.run_preview(previous=previous, batch_size=1)
            rows = self.candidates(result)
            current = {c['chunk_id'] for c in rows}
            self.assertTrue(ids.isdisjoint(current))
            ids.update(current)
            names.update(c['filename'] for c in rows)
            previous = result
            if not result['continuation']['has_more_in_current_retrieval']:
                break
        self.assertIn('unknown.txt', names)
        self.assertIn('known.txt', names)

    def test_continuation_accumulates_one_pending_checkpoint_generation(self):
        first = self.run_preview(batch_size=1)
        second = self.run_preview(previous=first, batch_size=1)
        first_checkpoint = first['exploration_checkpoint']
        second_checkpoint = second['exploration_checkpoint']
        self.assertEqual(second_checkpoint['generation'], first_checkpoint['generation'])
        self.assertEqual(
            second_checkpoint['parent_checkpoint_id'],
            first_checkpoint['parent_checkpoint_id'],
        )
        first_seen = {item['chunk_id'] for item in first_checkpoint['seen']}
        second_seen = {item['chunk_id'] for item in second_checkpoint['seen']}
        self.assertTrue(first_seen <= second_seen)

    def test_no_lexical_preference_overlap_does_not_block_exploration(self):
        preferences = dict(self.profile['finding_preferences'], preferred_kinds=['повседневная жизнь'])
        result = self.run_preview(changes={'finding_preferences': preferences})
        self.assertIn('unknown.txt', {c['filename'] for c in self.candidates(result)})
        first, _ = discovery_evidence('A baker carried a basket of bread to market and dropped it beside the bridge.\n\nA singer performed a melody for neighbours gathered in a courtyard after the meal.',
            dict(self.profile, finding_preferences=dict(preferred_kinds=['singer'])))
        self.assertTrue(first.startswith('A singer'))

    def test_spread_visits_every_position_and_rounds_do_not_starve_sources(self):
        indices = list(spread_indices(101))
        self.assertEqual(len(set(indices)), 101)
        self.assertEqual(set(indices), set(range(101)))
        self.assertGreater(max(indices[:7]), 80)
        self.assertLess(min(indices[:7]), 20)
        connection = sqlite3.connect(':memory:')
        self.addCleanup(connection.close)
        connection.row_factory = sqlite3.Row
        connection.execute('CREATE TABLE chunks (chunk_id TEXT, source TEXT, filename TEXT, relative_path TEXT, chunk_no INT, source_type TEXT, text_quality TEXT, is_duplicate INT, text_hash TEXT)')
        for source, size in [('Large', 101), ('Small', 3)]:
            connection.executemany('INSERT INTO chunks VALUES (?,?,?,?,?,?,?,?,?)',
                [(f'{source}-{n}', source, 'book.txt', f'{source}/book.txt', n, 'other', 'good', 0, f'hash-{source}-{n}') for n in range(size)])
        profile = dict(self.profile, exclude_sources=[])
        first, _ = discover_sources(connection, profile, set(), set(), document_group)
        self.assertEqual({row['source'] for row in first[:2]}, {'Large', 'Small'})
        later, _ = discover_sources(connection, profile, {first[0]['chunk_id']}, set(), document_group)
        self.assertEqual(later[0]['source'], 'Small')
        rejected = {row['chunk_id']: row['text_hash'] for row in first[:10]}
        remaining, _ = discover_sources(connection, profile, set(), set(), document_group, rejected)
        self.assertTrue(set(rejected).isdisjoint(row['chunk_id'] for row in remaining))
        connection.execute('UPDATE chunks SET text_hash=? WHERE chunk_id=?', ('changed', first[0]['chunk_id']))
        changed, _ = discover_sources(connection, profile, set(), set(), document_group, rejected)
        self.assertIn(first[0]['chunk_id'], {row['chunk_id'] for row in changed})

    def test_preview_is_read_only_and_missing_matches_are_not_fabricated_topics(self):
        before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in [self.database, self.used]}
        result = self.run_preview()
        self.assertEqual(before, {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in before})
        self.assertTrue(any(c['primary_topic'] is None for c in self.candidates(result)))

    def test_corrupt_discovery_state_fails_instead_of_silently_restarting(self):
        result = self.run_preview()
        result['continuation']['discovery_state_version'] = 999
        path = self.root / 'bad-continuation.json'
        path.write_text(json.dumps(result), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'версия'):
            research_findings.load_discovery_state([path])

    def test_registered_checkpoint_advances_daily_exploration_and_cycles(self):
        publications = self.root / 'checkpoint-publications'
        publications.mkdir(exist_ok=True)
        used = self.root / 'checkpoint-used.csv'
        used.write_text('id,type,persons,topics,short_description,source,date_used\n', encoding='utf-8')
        shown_by_edition = []
        checkpoints = []
        rejected_ids = set()
        rejected_by_edition = []
        first_cycle = None
        for number in range(1, 10):
            result = self.run_preview(
                batch_size=2, used_path=used, publications_path=publications
            )
            shown = result['exploration_checkpoint_status']['shown_via_source_exploration']
            self.assertTrue(shown)
            shown_by_edition.append(set(shown))
            checkpoints.append(result['exploration_checkpoint'])
            rejected_ids.update(
                item['chunk_id']
                for item in result['exploration_checkpoint']['rejected']
            )
            rejected_by_edition.append(set(
                result['exploration_checkpoint_status'][
                    'rejected_without_editorial_exposure'
                ]
            ))
            self.register_checkpoint(result, number, publications, used)
            first_cycle = first_cycle or result['exploration_checkpoint']['cycle']
            if result['exploration_checkpoint']['cycle'] > first_cycle:
                break

        self.assertGreater(checkpoints[-1]['cycle'], first_cycle)
        first_cycle_rows = [
            shown for shown, checkpoint in zip(shown_by_edition, checkpoints)
            if checkpoint['cycle'] == first_cycle
        ]
        accumulated = set()
        for shown in first_cycle_rows:
            self.assertTrue(accumulated.isdisjoint(shown))
            accumulated.update(shown)
        self.assertTrue(shown_by_edition[-1] & accumulated)
        self.assertTrue(rejected_ids)
        self.assertTrue(rejected_ids.isdisjoint(
            item['chunk_id'] for checkpoint in checkpoints for item in checkpoint['seen']
        ))
        first_cycle_rejections = [
            rejected for rejected, checkpoint in zip(rejected_by_edition, checkpoints)
            if checkpoint['cycle'] == first_cycle
        ]
        self.assertTrue(set().union(*first_cycle_rejections))
        for chunk_id in rejected_ids:
            self.assertLessEqual(
                sum(chunk_id in rejected for rejected in first_cycle_rejections), 1
            )

        latest, latest_path = daily_five.load_latest_registered_exploration_checkpoint(
            publications, used
        )
        self.assertEqual(latest['checkpoint_id'], checkpoints[-1]['checkpoint_id'])
        self.assertEqual(latest_path.name, f'edition-{len(checkpoints)}.json')
        # Idempotent replay seals the same checkpoint instead of creating progress.
        daily_five.record_publication_from_json(latest_path, used)
        daily_five.record_publication_from_json(publications / 'edition-1.json', used)
        replayed, _ = daily_five.load_latest_registered_exploration_checkpoint(
            publications, used
        )
        self.assertEqual(replayed['checkpoint_id'], latest['checkpoint_id'])

    def test_unregistered_checkpoint_is_ignored_and_thematic_search_is_not_bookmarked(self):
        publications = self.root / 'failure-publications'
        publications.mkdir(exist_ok=True)
        used = self.root / 'failure-used.csv'
        used.write_text('id,type,persons,topics,short_description,source,date_used\n', encoding='utf-8')
        first = self.run_preview(
            batch_size=2, used_path=used, publications_path=publications
        )
        self.register_checkpoint(first, 'registered', publications, used)
        second = self.run_preview(
            batch_size=10, used_path=used, publications_path=publications
        )
        known = next(
            item for item in self.candidates(second) if item['filename'] == 'known.txt'
        )
        self.assertIn('thematic_fts', known['retrieval']['methods'])

        draft = publications / 'failed-before-registration.json'
        draft.write_text(json.dumps({
            'publication_id': 'failed-before-registration',
            'exploration_checkpoint': second['exploration_checkpoint'],
            'cards': [{
                'id': 'ch_never_registered', 'type': 'event',
                'short_description': 'Not registered', 'source': 'Synthetic',
                'card_markdown': 'Not registered',
            }],
        }), encoding='utf-8')
        latest, _ = daily_five.load_latest_registered_exploration_checkpoint(
            publications, used
        )
        self.assertEqual(
            latest['checkpoint_id'], first['exploration_checkpoint']['checkpoint_id']
        )
        status = daily_five.publication_status_from_json(draft, used)
        self.assertFalse(status['registered'])
        self.assertFalse(status['exploration_checkpoint_registered'])
        with self.assertRaisesRegex(ValueError, 'record-publication'):
            daily_five.render_registered_publication_from_json(draft, used)

    def test_new_source_joins_an_existing_checkpoint_without_reset(self):
        connection = sqlite3.connect(':memory:')
        self.addCleanup(connection.close)
        connection.row_factory = sqlite3.Row
        connection.execute('CREATE TABLE chunks (chunk_id TEXT, source TEXT, filename TEXT, relative_path TEXT, chunk_no INT, source_type TEXT, text_quality TEXT, is_duplicate INT, text_hash TEXT)')
        connection.executemany('INSERT INTO chunks VALUES (?,?,?,?,?,?,?,?,?)', [
            ('old-1', 'Old', 'old.txt', 'Old/old.txt', 0, 'other', 'good', 0, 'old-hash-1'),
            ('old-2', 'Old', 'old.txt', 'Old/old.txt', 1, 'other', 'good', 0, 'old-hash-2'),
        ])
        profile = dict(self.profile, exclude_sources=[])
        seen = {'old-1': 'old-hash-1', 'old-2': 'old-hash-2'}
        before, _ = discover_sources(connection, profile, seen, set(), document_group)
        self.assertEqual(before, [])
        connection.execute('INSERT INTO chunks VALUES (?,?,?,?,?,?,?,?,?)',
            ('new-1', 'New', 'new.txt', 'New/new.txt', 0, 'other', 'good', 0, 'new-hash-1'))
        after, _ = discover_sources(connection, profile, seen, set(), document_group)
        self.assertEqual([row['chunk_id'] for row in after], ['new-1'])
        connection.execute(
            'UPDATE chunks SET text_hash=? WHERE chunk_id=?',
            ('old-hash-1-changed', 'old-1'),
        )
        changed, _ = discover_sources(connection, profile, seen, set(), document_group)
        self.assertIn('old-1', {row['chunk_id'] for row in changed})

    def test_profile_change_starts_a_new_checkpoint_cycle(self):
        publications = self.root / 'profile-change-publications'
        publications.mkdir(exist_ok=True)
        used = self.root / 'profile-change-used.csv'
        used.write_text('id,type,persons,topics,short_description,source,date_used\n', encoding='utf-8')
        first = self.run_preview(
            batch_size=2, used_path=used, publications_path=publications
        )
        self.register_checkpoint(first, 'old-profile', publications, used)
        changed = self.run_preview(
            batch_size=2, used_path=used, publications_path=publications,
            changes={'research_area': 'Changed synthetic area'},
        )
        self.assertTrue(changed['exploration_checkpoint_status']['profile_changed_reset'])
        self.assertEqual(
            changed['exploration_checkpoint']['generation'],
            first['exploration_checkpoint']['generation'] + 1,
        )
        self.assertEqual(
            changed['exploration_checkpoint']['cycle'],
            first['exploration_checkpoint']['cycle'] + 1,
        )

    def test_default_resume_directory_is_scoped_to_the_publication_journal(self):
        self.assertEqual(
            taira_search.exploration_manifests_path(
                taira_search.DEFAULT_USED_FINDS, None
            ),
            taira_search.DEFAULT_PUBLICATIONS.resolve(),
        )
        isolated = self.root / 'isolated-used.csv'
        self.assertEqual(
            taira_search.exploration_manifests_path(isolated, None),
            self.root / 'isolated-used.publications',
        )
        explicit = self.root / 'explicit-publications'
        self.assertEqual(
            taira_search.exploration_manifests_path(isolated, str(explicit)),
            explicit.resolve(),
        )
        with mock.patch(
            'daily_five.load_latest_registered_exploration_checkpoint',
            wraps=daily_five.load_latest_registered_exploration_checkpoint,
        ) as loader:
            self.run_preview(used_path=isolated, automatic_resume=True)
        self.assertEqual(
            loader.call_args.args[0], self.root / 'isolated-used.publications'
        )

    def test_pending_scope_and_unselected_person_cannot_be_registered(self):
        path = self.root / 'publication.json'
        journal = self.root / 'scope-used.csv'
        card = dict(chunk_id='ch_synthetic', type='event', persons=['Ada'], topics=[],
                    source='Synthetic', short_description='Synthetic story', card_markdown='Synthetic story')
        manifest = dict(publication_id='synthetic-scope', search_mode='focused_people',
                        focus_people=['Ada'], cards=[card])
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'scope_review'):
            daily_five.record_publication_from_json(path, journal)
        self.assertFalse(journal.exists())
        card['scope_review'] = dict(status='accepted', reason='Synthetic scope decision',
                focus_person='Someone else', evidence=[dict(chunk_id='ch_synthetic', quote='Ada acted.')])
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, 'focus_person'):
            daily_five.record_publication_from_json(path, journal)
        self.assertFalse(journal.exists())
        card['scope_review']['focus_person'] = 'Ada'
        path.write_text(json.dumps(manifest))
        daily_five.record_publication_from_json(path, journal)
        _, rendered = daily_five.render_registered_publication_from_json(path, journal)
        self.assertEqual(rendered, card['card_markdown'])

    def test_legacy_schema_fails_without_migration_or_backup(self):
        legacy = self.root / 'legacy.sqlite3'
        with contextlib.closing(sqlite3.connect(legacy)) as connection:
            connection.execute('CREATE TABLE meta (key TEXT, value TEXT)')
            connection.commit()
        before = legacy.read_bytes()
        with contextlib.redirect_stderr(io.StringIO()) as error:
            result = taira_search.main(['search', '--query', 'household', '--db', str(legacy)])
        self.assertEqual(result, 1)
        self.assertIn('схема', error.getvalue())
        self.assertEqual(legacy.read_bytes(), before)
        self.assertFalse(list(self.root.glob('legacy.sqlite3.*.bak')))


if __name__ == '__main__':
    unittest.main()
