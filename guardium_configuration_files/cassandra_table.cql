CREATE KEYSPACE movies WITH REPLICATION = { 'class' : 'SimpleStrategy',     'replication_factor' : 1 };

USE movies;

CREATE TABLE movie (id UUID PRIMARY KEY, m_title text, m_release int);

INSERT INTO movie (id, m_title, m_release) VALUES (uuid(), 'Alien', 1979);

INSERT INTO movie (id, m_title, m_release) VALUES (uuid(), 'Aliens', 1986);

INSERT INTO movie (id, m_title, m_release) VALUES (uuid(), 'Alien 3', 1992);

INSERT INTO movie (id, m_title, m_release) VALUES (uuid(), 'Alien: Resurrection', 1997);

INSERT INTO movie (id, m_title, m_release) VALUES (uuid(), 'Alien: Romulus', 2024);

INSERT INTO movie (id, m_title, m_release) VALUES (uuid(), 'Alien: Earth', 2025);

SELECT * FROM movie;
